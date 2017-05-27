# -*- coding: utf-8 -*-
import errno
import logging
import os
import select
import socket
import traceback

import service_socket

from common.pollables import pollable
from common.utilities import constants
from common.utilities import util


class ListenerSocket(pollable.Pollable):
    def __init__(self, socket, state, application_context, pollables):
        self._application_context = application_context
        self._socket = socket
        self._fd = socket.fileno()
        self._state = constants.LISTEN_STATE
        self._data_to_send = ""

        self._pollables = pollables

    @property
    def fd(self):
        return self._fd

    @property
    def socket(self):
        return self._socket

    @property
    def state(self):
        return self._state

    @property
    def data_to_send(self):
        return self._data_to_send

    @state.setter
    def state(self, s):
        self._state = s

    # state functions
    def listen_state(self):
        new_socket, address = self._socket.accept()

        # set to non blocking
        new_socket.setblocking(0)

        # add to database
        new_http_socket = service_socket.ServiceSocket(
            new_socket,
            constants.GET_REQUEST_STATE,
            self._application_context,
            self._pollables
        )
        self._pollables[new_socket.fileno()] = new_http_socket
        logging.debug(
            "%s :\t Added a new HttpSocket, %s"
            % (
                self,
                new_http_socket
            )
        )
        print "ADDING SOCKET: " + str(new_socket.fileno())

    def is_terminating(self):
        return self._state == constants.CLOSING_STATE

    def on_close(self):
        self._socket.close()

    # handlers:
    states = {
        constants.LISTEN_STATE: {
            "function": listen_state,
            "next": constants.CLOSING_STATE
        },
        constants.CLOSING_STATE: {
            "function": on_close,
            "next": constants.CLOSING_STATE,
        }
    }

    def on_read(self):
        try:
            if self._state == constants.LISTEN_STATE:
                self.listen_state()

        except Exception as e:
            logging.error("%s :\t %s" %
                          (
                              self,
                              traceback.print_exc()
                          )
                          )
            self.on_error()

    def on_error(self):
        self._state = constants.CLOSING_STATE

    def get_events(self):
        event = constants.POLLERR
        if (
            self._state == constants.LISTEN_STATE and
            len(self._pollables) < self._application_context["max_connections"]
        ):
            event |= constants.POLLIN
        return event

    def __repr__(self):
        return ("HttpListen Object: %s\t\t\t" % self._fd)
