#!/usr/bin/python
## @package RAID5.block_device.__main__
# Main module that runs the Block Device Server
#

import argparse
import ConfigParser
import errno
import logging
import os

# only posix has resource module (from supporable systems)
if os.name == "posix":
	import resource

import signal
import traceback

from common.utilities import async_server
from common.utilities import config_util
from common.utilities import constants
from common.utilities import poller
from common.utilities import util

if not hasattr(os, 'O_BINARY'):
    os.O_BINARY = 0

## Files
NEW_FILE = os.devnull
NEW_WORKING_DIRECTORY = "/"
NUMBER_OF_STANDARD_FILES = 3
LOG_FILE = "log"


## Poll types
POLL_TYPE = {
    "poll": poller.Poller,
    "select": poller.Select
}

## Parse Arguments for running the Block Device Server
def parse_args():
    """Parse program argument."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--bind-port',
        required=True,
        type=int,
        help='Bind port, default: %(default)s',
    )
    parser.add_argument(
        '--base',
        default='.',
        help='Base directory to search files in, default: %(default)s',
    )
    parser.add_argument(
        '--poll-timeout',
        type=int,
        default=constants.DEFAULT_BLOCK_POLL_TIMEOUT,
    )
    parser.add_argument(
        '--poll-type',
        choices=POLL_TYPE.keys(),
        default=sorted(POLL_TYPE.keys())[0],
        help='poll or select, default: poll'
    )
    parser.add_argument(
        '--max-buffer',
        type=int,
        default=constants.BLOCK_SIZE,
    )
    parser.add_argument(
        '--max-connections',
        type=int,
        default=1000,
    )
    parser.add_argument(
        '--config-file',
        type=str,
        required=True
    )
    parser.add_argument(
        '--log-file',
        type=str,
        default=None
    )
    parser.add_argument(
        '--daemon',
        type=bool,
        default=False,
    )
    args = parser.parse_args()
    args.base = os.path.normpath(os.path.realpath(args.base))
    return args

## Main Function that creates the AsyncServer and lets the server run
def main():
    args = parse_args()

    # delete the previous log
    try:
        if args.log_file is not None:
            os.remove(args.log_file)
    except BaseException:
        pass
    logging.basicConfig(filename=args.log_file, level=logging.DEBUG)

    # parse the config file
    config_sections = config_util.parse_config(args.config_file)

    # check that the disk file and dis info file is ok before running the
    # server create file if necessary
    try:
        disk_fd = os.open(
            config_sections["Server"]["disk_name"],
            os.O_RDONLY | os.O_CREAT | os.O_BINARY,
            0o666
        )
        os.close(disk_fd)
    except Exception as e:
        logging.critical("BLOCK DEVICE STARTUP UNSUCCESSFUL:\t %s" % e)
        return

    # handle daemon state
    if args.daemon:
        daemonize()

    application_context = {
        "server_type": constants.BLOCK_DEVICE_SERVER,
        "bind_address": constants.DEFAULT_HTTP_ADDRESS,
        "bind_port": args.bind_port,
        "base": args.base,
        "poll_type": POLL_TYPE[args.poll_type],
        "poll_timeout": args.poll_timeout,
        "max_connections": args.max_connections,
        "max_buffer": args.max_buffer,
        "disk_name": config_sections["Server"]["disk_name"],
        "disk_info_name": config_sections["Server"]["disk_info_name"],
        "multicast_group": config_sections["MulticastGroup"],
        "authentication": config_sections["Authentication"],
        "server_info": config_sections["Server"],
        "config_file": args.config_file,
    }
    server = async_server.AsyncServer(application_context)
    server.run()


def daemonize():
    if os.name == "nt":
        raise RuntimeError("Daemon not available on Windows...")

    child = os.fork()
    if child != 0:
        os._exit(0)

    import resource

    for i in range(3, resource.getrlimit(resource.RLIMIT_NOFILE)[1]):
        try:
            os.close(i)
        except OSError as e:
            if e.errno != errno.EBADF:
                raise

    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    fd = os.open(os.devnull, os.O_RDWR, 0o666)
    for i in range(3):
        os.dup2(i, fd)
    os.close(fd)
    child = os.fork()
    if child != 0:
        os._exit(0)


if __name__ == '__main__':
    main()


# vim: expandtab tabstop=4 shiftwidth=4
