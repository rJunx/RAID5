# -*- coding: utf-8 -*-
import argparse
import contextlib
import datetime
import errno
import fcntl
import os
import socket
import select
import sys
import time
import traceback

import http_socket
import poller

from ..common import constants
from ..common import util

# python-3 woodo
try:
    # try python-2 module name
    import urlparse
except ImportError:
    # try python-3 module name
    import urllib.parse
    urlparse = urllib.parse


(
    START_STATE,
    HEADERS_STATE,
    CONTENT_STATE,
    END_STATE,
) = range(4)

MIME_MAPPING = {
    'html': 'text/html',
    'png': 'image/png',
    'txt': 'text/plain',
}

#TODO: set closing after finished file
class Service(object):
    def __init__(
        self,
        wanted_headers,
        wanted_args = [],
        args = []
    ):
        self._wanted_headers = wanted_headers + ["Content-Length"]
        self._wanted_args = wanted_args
        self._response_headers = {}
        self._response_status = 200
        self._response_content = ""
        self._args = args

    @property
    def args(self):
        return self._args

    @args.setter
    def args(self, a):
        self._args = a

    @property
    def wanted_headers(self):
        return self._wanted_headers

    @wanted_headers.setter
    def wanted_headers(self, w_h):
        self._wanted_headers = w_h

    @property
    def wanted_args(self):
        return self._wanted_args

    @wanted_args.setter
    def wanted_args(self, w_a):
        self._wanted_args = w_a

    @property
    def response_status(self):
        return self._response_status

    @response_status.setter
    def response_status(self, r_s):
        self._response_status = r_s

    @property
    def response_headers(self):
        return self._response_headers

    @response_headers.setter
    def response_headers(self, r_h):
        self._response_headers = r_h

    @property
    def response_content(self):
        return self._response_content

    @response_content.setter
    def response_content(self, r_c):
        self._response_content = r_c

    def before_content(self, entry):
        return True

    def before_response_status(self, entry):
        return True

    def before_response_headers(self, entry):
        return True

    def before_response_content(self, entry, max_buffer):
        return True

    def before_terminate(self, entry):
        return True

    def handle_content(self, entry, content):
        pass

    def check_args(self):
        for arg in self._wanted_args:
            if arg not in self._args.keys():
                return False
        return len(self._wanted_args) == len(self._args)


class GetFileService(Service):
    def __init__(self, file_name):
        Service.__init__(self, [])
        self._file_name = file_name
        self._fd = None

    def before_response_status(self, entry):
        try:
            self._fd = os.open(self._file_name, os.O_RDONLY, 0o666)
        except Exception as e:
            self._response_status = 404
            raise RuntimeError("Problem opening file")
        return True

    def before_response_headers(self, entry):
        self._response_headers = {
            "Content-Length" : os.fstat(self._fd).st_size,
            "Content-Type" : MIME_MAPPING.get(
                os.path.splitext(
                    self._file_name
                )[1].lstrip('.'),
                'application/octet-stream',
            )
        }
        return True

    def before_response_content(
        self,
        entry,
        max_buffer = constants.BLOCK_SIZE
    ):
        buf = True
        try:
            while len(entry.data_to_send) < max_buffer:
                buf = os.read(self._fd, max_buffer)
                if not buf:
                    break
                self._response_content += buf

            if buf:
                return False
            os.close(self._fd)
            return True

        except socket.error, e:
            if e.errno != errno.EAGAIN and e.errno != errno.EWOULDBLOCK:
                raise


class TimeService(Service):
    def __init__(self):
        Service.__init__(self, [])
        #super(TimeService, self).__init__(self, [])


    def before_response_headers(self, entry):
        self._response_headers = {
            "Content-Length" : len(str(datetime.datetime.now())),
        }
        self._response_content = str(datetime.datetime.now())
        return True


class MulService(Service):
    def __init__(self, args):
        Service.__init__(self, [], ["a", "b"], args)
        #super(MulService, self).__init__(self, [], ["a", "b"], args)

    def before_response_status(self, entry):
        if not self.check_args():
            self._response_status = 500

    def before_response_headers(self, entry):
        if self._response_status == 200:
            resp = str(
                int(self._args['a'][0]) *
                int(self._args['b'][0])
            )
            self._response_headers = {
                "Content-Length" : len(resp)
            }
            self._response_content = resp
        return True

class FileFormService(Service):
    def __init__(self):
        Service.__init__(self, ["Content-Type"])
        #super(FileFormService, self).__init__(self, ["Content-Type"])
        self._content = ""
        self._boundary = None
        self._state = START_STATE
        self._fd = None

    def before_content(self, entry):
        content_type = entry.request_context["headers"]["Content-Type"]
        if (
            content_type.find("multipart/form-data") == -1 or
            content_type.find("boundary") == -1
        ):
            raise RuntimeError("Bad Form Request")
        self._boundary = content_type.split("boundary=")[1]

    def start_state(self):
        if self._content.find("--%s" % self._boundary) == -1:
            return False
        self._content = self._content.split(
            "--%s%s" % (
                self._boundary,
                constants.CRLF_BIN
            ), 1
        )[1]
        return True

    def headers_state(self):
        lines = self._content.split(constants.CRLF_BIN)
        if "" not in lines:
            return False

        #got all the headers, process them
        headers = {}
        for index in range(len(lines)):
            line = lines[index]
            if line == "":
                self._content = constants.CRLF_BIN.join(lines[index + 1:])
                break

            k, v = util.parse_header(line)
            headers[k] = v

        if "Content-Disposition" not in headers.keys():
            raise RuntimeError("Missing content-disposition header")

        self._filename = None
        disposition_fields = headers["Content-Disposition"].split("; ")[1:]
        for field in disposition_fields:
            name, info = field.split('=', 1)

            if name == "filename":
                self._filename = info

        try:
            self._fd = os.open(constants.TMP_FILE_NAME, os.O_RDWR | os.O_CREAT, 0o666)
        except Exception as e:
            raise RuntimeError("Problem opening file")
        return True

    def end_boundary(self):
        return "--%s--%s" % (
            self._boundary,
            constants.CRLF_BIN
        )

    def mid_boundary(self):
        return "--%s%s" % (
            self._boundary,
            constants.CRLF_BIN
        )

    def content_state(self):
        if self._content.find(self.end_boundary()) != -1:
            buf = self._content.split(self.end_boundary(), 1)[0]
            next_state = 2
        elif self._content.find(self.mid_boundary()) != -1:
            buf = self._content.split(self.mid_boundary(), 1)[0]
            next_state = 1
        else:
            buf = self._content
            next_state = 0

        self._content = self._content[len(buf):]
        if self._filename is not None:
            try:
                while buf:
                    buf = buf[os.write(self._fd, buf):]
            except Exception as e:
                if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                    raise
        self._content = buf + self._content

        if next_state == 1 and buf == "":
            self._content = self._content.split(self.end_boundary(), 1)[1]

        if next_state:
            os.rename(constants.TMP_FILE_NAME, self._filename)

        return next_state


    BOUNDARY_STATES = {
        START_STATE: {
            "function": start_state,
            "next": HEADERS_STATE,
        },
        HEADERS_STATE: {
            "function": headers_state,
            "next": CONTENT_STATE
        },
        CONTENT_STATE: {
            "function": content_state,
            "next": HEADERS_STATE,
        }
    }

    def handle_content(self, content):
        self._content += content
        while True:
            next_state = FileFormService.BOUNDARY_STATES[self._state]["function"](self)
            if (
                next_state == 0 or
                (self._state == CONTENT_STATE and next_state == 2)
            ):
                break
            self._state = FileFormService.BOUNDARY_STATES[self._state]["next"]

    def before_response_headers(self, entry):
        self._response_content = "File was uploaded successfully"
        self._response_headers = {
            "Content-Length" : len(self._response_content),
        }
        return True

    def before_response_content(
        self,
        entry,
        max_buffer = constants.BLOCK_SIZE
    ):
        return True


SERVICES = {
    "/clock": TimeService,
    "/mul" :  MulService,
}


'''
    references
    "/mul": {"name": mul, "headers": None},
    "/secret": {"name": secret, "headers": ["Authorization"]},
    "/cookie": {"name": cookie, "headers": ["Cookie"]},
    "/login": {"name": login, "headers": None},
    "/secret2": {"name": secret2, "headers": ["Cookie"]},
'''