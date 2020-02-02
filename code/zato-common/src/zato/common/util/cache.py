# -*- coding: utf-8 -*-

"""
Copyright (C) 2019, Zato Source s.r.o. https://zato.io

Licensed under LGPLv3, see LICENSE.txt for terms and conditions.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

# stdlib
import os
from json import dumps, loads

# Bunch
from bunch import bunchify

# Requests
import requests
from requests import Session as RequestsSession

# Zato
from zato.common import CACHE, NotGiven
from zato.common.crypto import ServerCryptoManager
from zato.common.util import as_bool, get_config, get_odb_session_from_server_config, get_repo_dir_from_component_dir
from zato.common.odb.model import Cluster, HTTPBasicAuth, Server

# ################################################################################################################################

if 0:
    from requests import Response as RequestsResponse

    RequestsResponse = RequestsResponse

# ################################################################################################################################

# Maps cache operations to HTTP verbos
op_verb_map = {
    'get': 'GET',
    'set': 'POST',
    'delete': 'DELETE'
}

# ################################################################################################################################
# ################################################################################################################################

class CommandConfig(object):
    __slots__ = 'command', 'modifier', 'key', 'value', 'is_string_key', 'is_int_key', 'is_string_value', 'is_int_value', \
        'is_bool_value', 'format'

    def __init__(self):
        self.command = None         # type: str
        self.modifier = None        # type: str
        self.key = None             # type: str
        self.value = None           # type: str
        self.is_string_key = None   # type: bool
        self.is_int_key = None      # type: bool
        self.is_string_value = None # type: bool
        self.is_int_value = None    # type: bool
        self.is_bool_value = None   # type: bool
        self.format = None          # type: str

    def to_dict(self):
        out = {}
        for name in self.__slots__:
            out[name] = getattr(self, name)
        return out

# ################################################################################################################################
# ################################################################################################################################

class CommandResponse(object):
    __slots__ = 'key', 'raw', 'data', 'has_value'

    def __init__(self):
        self.key = None       # type: object
        self.raw = None       # type: str
        self.data = None      # type: Bunch
        self.has_value = None # type: bool

# ################################################################################################################################
# ################################################################################################################################

class Client(object):
    """ An HTTP-based Zato cache client.
    """
    __slots__ = 'address', 'username', 'password', 'session'

    def __init__(self):
        self.address = None  # type: str
        self.username = None # type: str
        self.password = None # type: str
        self.session = None  # type: RequestsSession

# ################################################################################################################################

    @staticmethod
    def from_server_conf(server_dir, is_https):
        # type: (str, bool) -> Client
        repo_dir = get_repo_dir_from_component_dir(server_dir)
        cm = ServerCryptoManager.from_repo_dir(None, repo_dir, None)
        secrets_conf = get_config(repo_dir, 'secrets.conf', needs_user_config=False)
        config = get_config(repo_dir, 'server.conf', crypto_manager=cm, secrets_conf=secrets_conf)

        session = None
        password = None

        try:
            session = get_odb_session_from_server_config(config, None, False)

            cluster = session.query(Server).\
                filter(Server.token == config.main.token).\
                one().cluster # type: Cluster

            security = session.query(HTTPBasicAuth).\
                filter(Cluster.id == HTTPBasicAuth.cluster_id).\
                filter(HTTPBasicAuth.username == CACHE.API_USERNAME).\
                filter(HTTPBasicAuth.cluster_id == cluster.id).\
                first() # type: HTTPBasicAuth

            if security:
                password = security.password

        finally:
            if session:
                session.close()

        return Client.from_dict({
            'password': password,
            'address': config.main.gunicorn_bind,
            'is_https': is_https,
        })

# ################################################################################################################################

    @staticmethod
    def from_dict(config):
        # type: (dict) -> Client

        client = Client()
        client.username = CACHE.API_USERNAME
        client.password = config['password']
        client.address = 'http{}://{}'.format('s' if config['is_https'] else '', config['address'])

        session = RequestsSession()
        if client.password:
            session.auth = (client.username, client.password)
        client.session = session

        return client

# ################################################################################################################################

    def _request(self, op, key, value=NotGiven, pattern='/zato/cache/{}', op_verb_map=op_verb_map):
        # type: (str, str, str) -> str

        # Build a full address
        path = pattern.format(key)
        address = '{}{}'.format(self.address, path)

        # Get the HTTP verb to use in the request
        verb = op_verb_map[op] # type: str

        data = {'return_prev': True}

        if value is not NotGiven:
            data['value'] = value

        data = dumps(data)

        response = self.session.request(verb, address, data=data) # type: RequestsResponse
        return response.text

# ################################################################################################################################

    def run_command(self, config):
        # type: (CommandConfig) -> CommandResponse

        if config.is_int_key:
            key = int(config.key)
        else:
            key = config.key

        if config.is_int_value:
            value = int(config.value)
        elif config.is_bool_value:
            value = as_bool(config.value)
        else:
            value = config.value

        raw_response = self._request(config.command, key, value)

        response = loads(raw_response)
        response = bunchify(response)

        _response = CommandResponse()
        _response.key = config.key
        _response.raw = raw_response
        _response.data = response
        _response.has_value = 'value' in _response.data

        return _response

# ################################################################################################################################
# ################################################################################################################################
