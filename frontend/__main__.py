#!/usr/bin/python
## @package RAID5.frontend.__main__
# Main module that runs the Frontend Server
#

import argparse
import ConfigParser
import errno
import logging
import os

# only posix has resource module
if os.name == "posix":
	import resource

import signal
import traceback

from common.utilities import async_server
from common.utilities import config_util
from common.utilities import poller
from common.utilities import constants

if not hasattr(os, 'O_BINARY'):
    os.O_BINARY = 0

## Files
NEW_FILE = os.devnull
NEW_WORKING_DIRECTORY = "/"
LOG_FILE = "log"

## Poll types
POLL_TYPE = {
    "poll": poller.Poller,
    "select": poller.Select
}

## Parse Arguments for running the Frontend Server
def parse_args():
    """Parse program argument."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--bind-address',
        default=constants.DEFAULT_HTTP_ADDRESS,
        help='Bind address, default: %(default)s',
    )
    parser.add_argument(
        '--bind-port',
        default=constants.DEFAULT_FRONTEND_HTTP_PORT,
        type=int,
        help='Bind port, default: %(default)s',
    )
    parser.add_argument(
        '--base',
        default=constants.DEFAULT_BASE_DIRECTORY,
        help='Base directory to search files in, default: %(default)s',
    )
    parser.add_argument(
        '--poll-timeout',
        type=int,
        default=constants.DEFAULT_FRONTEND_POLL_TIMEOUT,
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
        '--log-file',
        type=str,
        default=None,
    )
    parser.add_argument(
        '--config-file',
        type=str,
        required=True,
    )
    parser.add_argument(
        '--daemon',
        type=bool,
        default=False,
    )
    args = parser.parse_args()
    args.base = os.path.normpath(os.path.realpath(args.base))
    return args

## Main Function that creates the AsyncServer and lets the server run. creates
## also the volumes that are saved in the configuration file.
def main():
    # parse args
    args = parse_args()
    # parse the config file
    config_sections = config_util.parse_config(args.config_file)

    # delete the previous log
    try:
        os.remove(args.log_file)
    except BaseException:
        pass
    logging.basicConfig(filename=args.log_file, level=logging.DEBUG)

    # create volumes out of volume_UUID's in config_file, might
    # be recreated
    volumes = {}
    for section, content in config_sections.items():
        if "volume" in section:
            volumes[content["volume_uuid"]] = {
                "volume_UUID": content["volume_uuid"],
                "volume_state": constants.UNINITIALIZED,
                "long_password": content["long_password"],
                "disks": {},
            }

    # handle daemon state
    if args.daemon:
        daemonize()

    # create opplication context from config_file and args
    application_context = {
        "bind_address": args.bind_address,
        "bind_port": args.bind_port,
        "base": args.base,
        "poll_type": POLL_TYPE[args.poll_type],
        "poll_timeout": args.poll_timeout,
        "max_connections": args.max_connections,
        "max_buffer": args.max_buffer,
        "server_type": constants.FRONTEND_SERVER,
        "volumes": volumes,
        "available_disks": {},
        "multicast_group": config_sections["MulticastGroup"],
        "authentication": config_sections["Authentication"],
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
