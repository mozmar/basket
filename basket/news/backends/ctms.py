"""
API Client Library for Mozilla's Contact Management System (CTMS)
https://github.com/mozilla-it/ctms-api/
"""

from functools import cached_property, partialmethod
from urllib.parse import urlparse, urlunparse, urljoin

from django.conf import settings
from django.core.cache import cache

from requests_oauthlib import OAuth2Session
from oauthlib.oauth2 import BackendApplicationClient

from basket.news.backends.common import get_timer_decorator

time_request = get_timer_decorator("news.backends.ctms")

# Map CTMS group / name pairs to basket flat format names
# Missing basket names from SFDC integration:
#  record_type
#  postal_code
#  source_url
#  fsa_*
#  cv_*
#  amo_deleted
#  payee_id
#  fxa_last_login
CTMS_TO_BASKET_NAMES = {
    "amo": {
        "add_on_ids": None,
        "display_name": "amo_display_name",
        "email_opt_in": None,
        "language": None,
        "last_login": "amo_last_login",
        "location": "amo_location",
        "profile_url": "amo_homepage",
        "user": "amo_user",
        "user_id": "amo_id",
        "username": None,
        "create_timestamp": None,
        "update_timestamp": None,
    },
    "email": {
        "primary_email": "email",
        "basket_token": "token",
        "double_opt_in": "optin",
        "sfdc_id": "id",
        "first_name": "first_name",
        "last_name": "last_name",
        "mailing_country": "country",
        "email_format": "format",
        "email_lang": "lang",
        "has_opted_out_of_email": "optout",
        "unsubscribe_reason": "reason",
        "email_id": "email_id",
        "create_timestamp": "created_date",
        "update_timestamp": "last_modified_date",
    },
    "fxa": {
        "fxa_id": "fxa_id",
        "primary_email": "fxa_primary_email",
        "created_date": "fxa_create_date",
        "lang": "fxa_lang",
        "first_service": "fxa_service",
        "account_deleted": "fxa_deleted",
    },
    "mofo": {
        # Need more information about the future MoFo integrations
        "mofo_email_id": None,
        "mofo_contact_id": None,
        "mofo_relevant": None,
    },
    "vpn_waitlist": {"geo": "fpn_country", "platform": "fpn_platform"},
}


def from_vendor(contact):
    """Convert CTMS nested data to basket key-value format

    @params contact: CTMS data
    @return: dict in basket format
    """
    data = {}
    for group_name, group in contact.items():
        basket_group = CTMS_TO_BASKET_NAMES.get(group_name)
        if basket_group:
            for ctms_name, basket_name in basket_group.items():
                if basket_name and ctms_name in group:
                    data[basket_name] = group[ctms_name]
        elif group_name == "newsletters":
            # Import newsletter names
            # Unimported per-newsletter data: format, language, source, unsub_reason
            newsletters = []
            for newsletter in group:
                if newsletter["subscribed"]:
                    newsletters.append(newsletter["name"])
            data["newsletters"] = newsletters
        else:
            pass
    return data


class CTMSSession:
    """Add authentication to requests to the CTMS API"""

    def __init__(
        self, api_url, client_id, client_secret, token_cache_key="ctms_token",
    ):
        """Initialize a CTMSSession

        @param api_url: The base API URL (protocol and domain)
        @param client_id: The CTMS client_id for OAuth2
        @param client_secret: The CTMS client_secret for OAuth2
        @param token_cache_key: The cache key to store access tokens
        """
        urlbits = urlparse(api_url)
        if not urlbits.scheme or not urlbits.netloc:
            raise ValueError("Invalid api_url")
        self.api_url = urlunparse((urlbits.scheme, urlbits.netloc, "", "", "", ""))

        if not client_id:
            raise ValueError("client_id is empty")
        self.client_id = client_id

        if not client_secret:
            raise ValueError("client_secret is empty")
        self.client_secret = client_secret

        if not token_cache_key:
            raise ValueError("client_secret is empty")
        self.token_cache_key = token_cache_key

    @property
    def _token(self):
        """Get the current OAuth2 token"""
        return cache.get(self.token_cache_key)

    def save_token(self, token):
        """Set the OAuth2 token"""
        expires_in = int(token.get("expires_in", 60))
        timeout = int(expires_in * 0.95)
        cache.set(self.token_cache_key, token, timeout=timeout)

    @_token.setter
    def _token(self, token):
        self.save_token(token)

    @classmethod
    def check_2xx_response(cls, response):
        """Raise an error for a non-2xx response"""
        response.raise_for_status()
        return response

    @cached_property
    def _session(self):
        """Get an authenticated OAuth2 session"""
        client = BackendApplicationClient(client_id=self.client_id)
        session = OAuth2Session(
            client=client,
            token=self._token,
            auto_refresh_url=urljoin(self.api_url, "/token"),
            auto_refresh_kwargs={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            token_updater=self.save_token,
        )
        session.register_compliance_hook(
            "access_token_response", CTMSSession.check_2xx_response
        )
        session.register_compliance_hook(
            "refresh_token_response", CTMSSession.check_2xx_response
        )
        if not session.authorized:
            session = self._authorize_session(session)
        return session

    def _authorize_session(self, session):
        """Fetch a client-crendetials token and add to the session."""
        self._token = session.fetch_token(
            token_url=urljoin(self.api_url, "/token"),
            client_id=self.client_id,
            client_secret=self.client_secret,
        )
        return session

    def request(self, method, path, *args, **kwargs):
        """
        Request a CTMS API endpoint, with automatic token refresh.

        CTMS doesn't implement a refresh token endpoint (yet?), so we can't use
        the OAuth2Session auto-refresh features.

        @param method: the HTTP method, like 'GET'
        @param path: the path on the server, starting with a slash
        @param *args: positional args for requests.request
        @param **kwargs: keyword arge for requests.request. Important ones are
            params (for querystring parameters) and json (for the JSON-encoded
            body).
        @return a requests Response
        """
        session = self._session
        url = urljoin(self.api_url, path)
        resp = session.request(method, url, *args, **kwargs)
        if resp.status_code == 401:
            self._session = self._authorize_session(session)
            resp = session.request(method, url, *args, **kwargs)
        return resp

    get = partialmethod(request, "GET")
    post = partialmethod(request, "POST")
    put = partialmethod(request, "PUT")


class CTMSInterface:
    """Basic Interface to the CTMS API"""

    # Identifiers that uniquely identity a CTMS record
    unique_ids = [
        "email_id",
        "basket_token",
        "primary_email",
        "sfdc_id",
        "fxa_id",
        "mofo_email_id",
    ]
    # Identifiers that can be shared by multiple CTMS records
    shared_ids = ["mofo_contact_id", "amo_user_id", "fxa_primary_email"]
    all_ids = unique_ids + shared_ids

    def __init__(self, session):
        self.session = session

    @time_request
    def get_by_alternate_id(
        self,
        email_id=None,
        primary_email=None,
        basket_token=None,
        sfdc_id=None,
        fxa_id=None,
        mofo_email_id=None,
        mofo_contact_id=None,
        amo_user_id=None,
        fxa_primary_email=None,
    ):
        """
        Call GET /ctms to get a list of contacts matching all alternate IDs.

        @param email_id: CTMS email ID
        @param primary_email: User's primary email
        @param basket_token: Basket's token
        @param sfdc_id: Legacy SalesForce.com ID
        @param fxa_id: Firefox Accounts ID
        @param mofo_email_id: Mozilla Foundation email ID
        @param mofo_contact_id: Mozilla Foundation contact ID
        @param amo_user_id: User ID from addons.mozilla.org
        @param fxa_primary_email: Primary email in Firefox Accounts
        @return: list of contact dicts
        @raises: request.HTTPError, status_code 400, on bad auth credentials
        @raises: request.HTTPError, status_code 401, on no auth credentials
        @raises: request.HTTPError, status_code 404, on unknown email_id
        """

        ids = {}
        for name, value in locals().items():
            if name in self.all_ids and value is not None:
                ids[name] = value
        if not ids:
            raise ValueError("At least one ID must be non-null")
        resp = self.session.get("/ctms", params=ids)
        resp.raise_for_status()
        return resp.json()

    @time_request
    def post_to_create(self, data):
        """
        Call POST /ctms to create a contact.

        The email (email.primary_email) is the only required item. If the CTMS
        email_id is not set (email.email_id), the server will generate one. Any
        unspecified value will be set to a default.

        @param data: The contact data, as a nested dictionary
        @return: The created contact data
        """
        resp = self.session.post("/ctms", json=data)
        resp.raise_for_status()
        return resp.json()

    @time_request
    def get_by_email_id(self, email_id):
        """
        Call GET /ctms/{email_id} to get contact data by CTMS email_id.

        @param email_id: The CTMS email_id of the contact
        @return: The contact data
        @raises: request.HTTPError, status_code 400, on bad auth credentials
        @raises: request.HTTPError, status_code 401, on no auth credentials
        @raises: request.HTTPError, status_code 404, on unknown email_id
        """
        resp = self.session.get(f"/ctms/{email_id}")
        resp.raise_for_status()
        return resp.json()

    @time_request
    def put_by_email_id(self, email_id, data):
        """
        Call PUT /ctms/{email_id} to replace a CTMS contact by ID

        @param email_id: The CTMS email_id of the contact
        @param data: The new or updated contact data
        @return: The created or replaced contact data
        """
        resp = self.session.put(f"/ctms/{email_id}", json=data)
        resp.raise_for_status()
        return resp.json()

    def put(self, data):
        """
        Call PUT /ctms/{email_id} to replace a CTMS contact, using email_id from data

        @return: The created or replaced contact data
        """
        email_id = data["email"]["email_id"]
        return self.put_by_email_id(email_id, data)


class CTMS:
    """Basket interface to CTMS"""

    def __init__(self, interface):
        self.interface = interface

    def get(
        self,
        email_id=None,
        token=None,
        email=None,
        sfdc_id=None,
        fxa_id=None,
        mofo_email_id=None,
        amo_id=None,
    ):
        """
        Get a contact record, using the first ID provided.

        @param email_id: CTMS email ID
        @param token: external ID
        @param email: email address
        @param sfdc_id: legacy SFDC ID
        @param fxa_id: external ID from FxA
        @param mofo_email_id: external ID from MoFo
        @param amo_id: external ID from AMO
        @return: dict, or None if disabled
        """
        if not self.interface:
            return None

        if email_id:
            contact = self.interface.get_by_email_id(email_id)
        else:
            if token:
                params = {"basket_token": token}
            elif email:
                params = {"primary_email": email}
            elif sfdc_id:
                params = {"sfdc_id": sfdc_id}
            elif fxa_id:
                params = {"fxa_id": fxa_id}
            elif mofo_email_id:
                params = {"mofo_email_id": mofo_email_id}
            elif amo_id:
                params = {"amo_user_id": amo_id}
            else:
                raise RuntimeError("One of the arguments must be set")

            contacts = self.interface.get_by_alternate_id(**params)
            if not contacts:
                contact = None
            elif len(contacts) == 1:
                contact = contacts[0]
            else:
                raise RuntimeError(f"Multiple contacts returned for {params}")

        if contact:
            return from_vendor(contact)
        else:
            return None


def ctms_session():
    """Return a CTMSSession configured from Django settings."""
    if settings.CTMS_ENABLED:
        return CTMSSession(
            api_url=settings.CTMS_URL,
            client_id=settings.CTMS_CLIENT_ID,
            client_secret=settings.CTMS_CLIENT_SECRET,
        )
    else:
        return None


def ctms_interface():
    """Return a CTMSInterface configured from Django settings."""
    session = ctms_session()
    if session:
        return CTMSInterface(session)
    else:
        return None


ctms = CTMS(ctms_interface())
