# Copyright (c) 2016, Neil Booth
#
# All rights reserved.
#
# See the file "LICENCE" for information about the copyright
# and warranty status of this software.

'''Server controller.

Coordinates the parts of the server.  Serves as a cache for
client-serving data such as histories.
'''

import asyncio
import ssl
from functools import partial

from server.daemon import Daemon
from server.block_processor import BlockProcessor
from server.protocol import ElectrumX, LocalRPC, JSONRPC
from lib.util import LoggedClass


class Controller(LoggedClass):

    def __init__(self, loop, env):
        '''Create up the controller.

        Creates DB, Daemon and BlockProcessor instances.
        '''
        super().__init__()
        self.loop = loop
        self.env = env
        self.coin = env.coin
        self.daemon = Daemon(env.daemon_url, env.debug)
        self.block_processor = BlockProcessor(env, self.daemon,
                                              on_update=self.on_update)
        JSONRPC.init(self.block_processor, self.daemon, self.coin)
        self.servers = []

    def start(self):
        '''Prime the event loop with asynchronous jobs.'''
        coros = self.block_processor.coros()

        for coro in coros:
            asyncio.ensure_future(coro)

    async def on_update(self, height, touched):
        if not self.servers:
            self.servers = await self.start_servers()
        ElectrumX.notify(height, touched)

    async def start_servers(self):
        '''Start listening on RPC, TCP and SSL ports.

        Does not start a server if the port wasn't specified.  Does
        nothing if servers are already running.
        '''
        servers = []
        env = self.env
        loop = self.loop

        protocol = LocalRPC
        if env.rpc_port is not None:
            host = 'localhost'
            rpc_server = loop.create_server(protocol, host, env.rpc_port)
            servers.append(await rpc_server)
            self.logger.info('RPC server listening on {}:{:d}'
                             .format(host, env.rpc_port))

        protocol = partial(ElectrumX, env)
        if env.tcp_port is not None:
            tcp_server = loop.create_server(protocol, env.host, env.tcp_port)
            servers.append(await tcp_server)
            self.logger.info('TCP server listening on {}:{:d}'
                             .format(env.host, env.tcp_port))

        if env.ssl_port is not None:
            # FIXME: update if we want to require Python >= 3.5.3
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
            ssl_context.load_cert_chain(env.ssl_certfile,
                                        keyfile=env.ssl_keyfile)
            ssl_server = loop.create_server(protocol, env.host, env.ssl_port,
                                            ssl=ssl_context)
            servers.append(await ssl_server)
            self.logger.info('SSL server listening on {}:{:d}'
                             .format(env.host, env.ssl_port))

        return servers

    def stop(self):
        '''Close the listening servers.'''
        for server in self.servers:
            server.close()