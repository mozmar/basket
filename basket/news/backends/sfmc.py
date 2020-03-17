"""
API Client Library for Salesforce Marketing Cloud (SFMC)
Formerly ExactTarget
"""
from random import randint
from time import time

from django.conf import settings
from django.core.cache import cache
from django.utils.encoding import force_str

import requests
from django_statsd.clients import statsd
from FuelSDK import ET_Client, ET_DataExtension_Row, ET_TriggeredSend

from basket.news.backends.common import get_timer_decorator, NewsletterException, \
                                 NewsletterNoResultsException


time_request = get_timer_decorator('news.backends.sfmc')


HERD_TIMEOUT = 60
AUTH_BUFFER = 300  # 5 min
MAX_BUFFER = HERD_TIMEOUT + AUTH_BUFFER


class ETRefreshClient(ET_Client):
    token_cache_key = 'backends:sfmc:auth:tokens'
    authTokenExpiresIn = None
    token_property_names = [
        'authToken',
        'authTokenExpiration',
        'internalAuthToken',
        'refreshKey',
    ]
    _old_authToken = None

    def __init__(self, get_server_wsdl=False, debug=False, params=None):
        # setting this manually as it has thrown errors and doesn't change
        if settings.USE_SANDBOX_BACKEND:
            self.endpoint = 'https://webservice.test.exacttarget.com/Service.asmx'
        else:
            self.endpoint = 'https://webservice.s4.exacttarget.com/Service.asmx'

        super(ETRefreshClient, self).__init__(get_server_wsdl, debug, params)

    def token_is_expired(self):
        """Report token is expired between 5 and 6 minutes early

        Having the expiration be random helps prevent multiple basket
        instances simultaneously requesting a new token from SFMC,
        a.k.a. the Thundering Herd problem.
        """
        if self.authTokenExpiration is None:
            return True

        time_buffer = randint(1, HERD_TIMEOUT) + AUTH_BUFFER
        return time() + time_buffer > self.authTokenExpiration

    def refresh_auth_tokens_from_cache(self):
        """Refresh the auth token and other values from cache"""
        if self.authToken is not None and time() + MAX_BUFFER < self.authTokenExpiration:
            # no need to refresh if the current tokens are still good
            return

        tokens = cache.get(self.token_cache_key)
        if tokens:
            if not isinstance(tokens, dict):
                # something wrong was cached
                cache.delete(self.token_cache_key)
                return

            for prop, value in tokens.items():
                if prop in self.token_property_names:
                    setattr(self, prop, value)

            # set the value so we can detect if it changed later
            self._old_authToken = self.authToken
            self.build_soap_client()

    def cache_auth_tokens(self):
        if self.authToken is not None and self.authToken != self._old_authToken:
            new_tokens = {prop: getattr(self, prop) for prop in self.token_property_names}
            # 10 min longer than expiration so that refreshKey can be used
            cache.set(self.token_cache_key, new_tokens, self.authTokenExpiresIn + 600)

    def request_token(self, payload):
        r = requests.post(self.auth_url, json=payload)
        try:
            token_response = r.json()
        except ValueError:
            raise NewsletterException('SFMC Error During Auth: ' + force_str(r.content),
                                      status_code=r.status_code)

        if 'accessToken' in token_response:
            return token_response

        # try again without refreshToken
        if 'refreshToken' in payload:
            # not strictly required, makes testing easier
            payload = payload.copy()
            del payload['refreshToken']
            return self.request_token(payload)

        raise NewsletterException('SFMC Error During Auth: ' + force_str(r.content),
                                  status_code=r.status_code)

    def refresh_token(self, force_refresh=False):
        """
        Called from many different places right before executing a SOAP call
        """
        # If we don't already have a token or the token expires within 5 min(300 seconds), get one
        self.refresh_auth_tokens_from_cache()
        if force_refresh or self.authToken is None or self.token_is_expired():
            payload = {
                'clientId': self.client_id,
                'clientSecret': self.client_secret,
                'accessType': 'offline',
            }
            if self.refreshKey:
                payload['refreshToken'] = self.refreshKey

            token_response = self.request_token(payload)
            statsd.incr('news.backends.sfmc.auth_token_refresh')
            self.authToken = token_response['accessToken']
            self.authTokenExpiresIn = token_response['expiresIn']
            self.authTokenExpiration = time() + self.authTokenExpiresIn
            self.internalAuthToken = token_response['legacyToken']
            if 'refreshToken' in token_response:
                self.refreshKey = token_response['refreshToken']

            self.build_soap_client()
            self.cache_auth_tokens()


def assert_response(resp):
    if not resp.status:
        raise NewsletterException(str(resp.results))


def assert_results(resp):
    assert_response(resp)
    if not resp.results:
        raise NewsletterNoResultsException()


def build_attributes(data):
    return [{'Name': key, 'Value': value} for key, value in data.items()]


class SFMC(object):
    _client = None
    sms_api_url = 'https://www.exacttargetapis.com/sms/v1/messageContact/{}/send'
    rowset_api_url = 'https://www.exacttargetapis.com/hub/v1/dataevents/key:{}/rowset'

    @property
    def client(self):
        if self._client is None and 'clientid' in settings.SFMC_SETTINGS:
            self._client = ETRefreshClient(False, settings.SFMC_DEBUG, settings.SFMC_SETTINGS)

        return self._client

    @property
    def auth_header(self):
        self.client.refresh_token()
        return {'Authorization': 'Bearer {0}'.format(self.client.authToken)}

    def _get_row_obj(self, de_name, props):
        row = ET_DataExtension_Row()
        row.auth_stub = self.client
        row.CustomerKey = row.Name = de_name
        row.props = props
        return row

    @time_request
    def get_row(self, de_name, fields, token=None, email=None):
        """
        Get the values of `fields` from a data extension. Either token or email is required.

        @param de_name: name of the data extension
        @param fields: list of column names
        @param token: the user's token
        @param email: the user's email address
        @return: dict of user data
        """
        assert token or email, 'token or email required'
        row = self._get_row_obj(de_name, fields)
        if token:
            row.search_filter = {
                'Property': 'TOKEN',
                'SimpleOperator': 'equals',
                'Value': token,
            }
        elif email:
            row.search_filter = {
                'Property': 'EMAIL_ADDRESS_',
                'SimpleOperator': 'equals',
                'Value': email,
            }

        resp = row.get()
        assert_results(resp)
        # TODO do something if more than 1 result is returned
        return dict((p.Name, p.Value)
                    for p in resp.results[0].Properties.Property)

    @time_request
    def add_row(self, de_name, values):
        """
        Add a row to a data extension.

        @param de_name: name of the data extension
        @param values: dict containing the COLUMN: VALUE pairs
        @return: None
        """
        row = self._get_row_obj(de_name, values)
        resp = row.post()
        assert_response(resp)

    @time_request
    def update_row(self, de_name, values):
        """
        Update a row in a data extension.

        @param de_name: name of the data extension
        @param values: dict containing the COLUMN: VALUE pairs.
            Must contain TOKEN or EMAIL_ADDRESS_.
        @return: None
        """
        row = self._get_row_obj(de_name, values)
        resp = row.patch()
        assert_response(resp)

    @time_request
    def upsert_row(self, de_name, values):
        """
        Add or update a row in a data extension.

        @param de_name: name of the data extension
        @param values: dict containing the COLUMN: VALUE pairs.
            Must contain TOKEN or EMAIL_ADDRESS_.
        @return: None
        """
        row = self._get_row_obj(de_name, values)
        resp = row.patch(True)
        assert_response(resp)

    @time_request
    def delete_row(self, de_name, column, value):
        """
        Delete a row from a data extension. Either token or email are required.

        @param de_name: name of the data extension
        @param token: user's token
        @param email: user's email address
        @return: None
        """
        row = self._get_row_obj(de_name, {column: value})
        resp = row.delete()
        assert_response(resp)

    @time_request
    def send_mail(self, ts_name, email, subscriber_key, token=None):
        """
        Send an email message to a user (Triggered Send).

        @param ts_name: the name of the message to send
        @param email: the email address of the user
        @param subscriber_key: the key for the user in SFMC
        @param format: T or H for Text or HTML
        @param token: optional token if a recovery message
        @return: None
        """
        ts = ET_TriggeredSend()
        ts.auth_stub = self.client
        ts.props = {'CustomerKey': ts_name}
        subscriber = {
            'EmailAddress': email,
            'SubscriberKey': subscriber_key,
        }
        if token:
            ts.attributes = build_attributes({
                'Token__c': token,
            })
            subscriber['Attributes'] = ts.attributes
        ts.subscribers = [subscriber]
        resp = ts.send()
        assert_response(resp)

    @time_request
    def send_sms(self, phone_numbers, message_id):
        if isinstance(phone_numbers, str):
            phone_numbers = [phone_numbers]

        phone_numbers = [pn.lstrip('+') for pn in phone_numbers]
        data = {
            'mobileNumbers': phone_numbers,
            'Subscribe': True,
            'Resubscribe': True,
            'keyword': 'FFDROID',  # TODO: Set keyword in arguments.
        }
        url = self.sms_api_url.format(message_id)
        response = requests.post(url, json=data, headers=self.auth_header, timeout=10)
        if response.status_code >= 500:
            raise NewsletterException('SFMC Server Error: {}'.format(force_str(response.content)),
                                      status_code=response.status_code)

        if response.status_code >= 400:
            raise NewsletterException('SFMC Request Error: {}'.format(force_str(response.content)),
                                      status_code=response.status_code)

    @time_request
    def bulk_upsert_rows(self, de_name, values):
        url = self.rowset_api_url.format(de_name)
        response = requests.post(url, json=values, headers=self.auth_header, timeout=30)
        if response.status_code >= 500:
            raise NewsletterException('SFMC Server Error: {}'.format(force_str(response.content)),
                                      status_code=response.status_code)

        if response.status_code >= 400:
            raise NewsletterException(force_str(response.content), status_code=response.status_code)


sfmc = SFMC()
