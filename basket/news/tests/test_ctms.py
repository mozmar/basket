import json
from unittest.mock import patch, Mock, ANY, DEFAULT
from uuid import uuid4

from django.test import TestCase
from django.test.utils import override_settings

from requests import Request, Response
from requests.exceptions import HTTPError

from basket.news.backends.ctms import (
    ctms_session,
    CTMS,
    CTMSInterface,
    CTMSSession,
    from_vendor,
    to_vendor,
)

# Sample CTMS response from documentation, April 2021
SAMPLE_CTMS_RESPONSE = json.loads(
    """
{
  "amo": {
    "add_on_ids": "add-on-1,add-on-2",
    "display_name": "Add-ons Author",
    "email_opt_in": false,
    "language": "en",
    "last_login": "2021-01-28",
    "location": "California",
    "profile_url": "firefox/user/98765",
    "user": true,
    "user_id": "98765",
    "username": "AddOnAuthor",
    "create_timestamp": "2020-12-05T19:21:50.908000+00:00",
    "update_timestamp": "2021-02-04T15:36:57.511000+00:00"
  },
  "email": {
    "primary_email": "contact@example.com",
    "basket_token": "c4a7d759-bb52-457b-896b-90f1d3ef8433",
    "double_opt_in": true,
    "sfdc_id": "001A000023aABcDEFG",
    "first_name": "Jane",
    "last_name": "Doe",
    "mailing_country": "us",
    "email_format": "H",
    "email_lang": "en",
    "has_opted_out_of_email": false,
    "unsubscribe_reason": "string",
    "email_id": "332de237-cab7-4461-bcc3-48e68f42bd5c",
    "create_timestamp": "2020-03-28T15:41:00.000Z",
    "update_timestamp": "2021-01-28T21:26:57.511Z"
  },
  "fxa": {
    "fxa_id": "6eb6ed6ac3b64259968aa490c6c0b9df",
    "primary_email": "my-fxa-acct@example.com",
    "created_date": "2021-01-29T18:43:49.082375+00:00",
    "lang": "en,en-US",
    "first_service": "sync",
    "account_deleted": false
  },
  "mofo": {
    "mofo_email_id": "string",
    "mofo_contact_id": "string",
    "mofo_relevant": false
  },
  "newsletters": [
    {
      "name": "mozilla-welcome",
      "subscribed": true,
      "format": "H",
      "lang": "en",
      "source": "https://www.mozilla.org/en-US/",
      "unsub_reason": "string"
    }
  ],
  "vpn_waitlist": {
    "geo": "fr",
    "platform": "ios,mac"
  },
  "status": "ok"
}
"""
)

SAMPLE_BASKET_FORMAT = {
    "amo_display_name": "Add-ons Author",
    "amo_homepage": "firefox/user/98765",
    "amo_id": "98765",
    "amo_last_login": "2021-01-28",
    "amo_location": "California",
    "amo_user": True,
    "country": "us",
    "created_date": "2020-03-28T15:41:00.000Z",
    "email": "contact@example.com",
    "email_id": "332de237-cab7-4461-bcc3-48e68f42bd5c",
    "first_name": "Jane",
    "format": "H",
    "fpn_country": "fr",
    "fpn_platform": "ios,mac",
    "fxa_create_date": "2021-01-29T18:43:49.082375+00:00",
    "fxa_deleted": False,
    "fxa_id": "6eb6ed6ac3b64259968aa490c6c0b9df",
    "fxa_lang": "en,en-US",
    "fxa_primary_email": "my-fxa-acct@example.com",
    "fxa_service": "sync",
    "id": "001A000023aABcDEFG",
    "lang": "en",
    "last_modified_date": "2021-01-28T21:26:57.511Z",
    "last_name": "Doe",
    "newsletters": ["mozilla-welcome"],
    "optin": True,
    "optout": False,
    "reason": "string",
    "token": "c4a7d759-bb52-457b-896b-90f1d3ef8433",
}


class FromVendorTests(TestCase):
    def test_sample_response(self):
        """The sample CTMS user can be converted to basket format"""
        data = from_vendor(SAMPLE_CTMS_RESPONSE)
        assert data == SAMPLE_BASKET_FORMAT

    def test_unknown_groups(self):
        """Unknown CTMS data groups are ignored."""
        ctms_contact = {
            "email": {
                "primary_email": "test@example.com",
                "basket_token": "basket-token",
            },
            "favorites": {"color": "blue", "album": "green", "mattress": "purple"},
        }
        data = from_vendor(ctms_contact)
        assert data == {"email": "test@example.com", "token": "basket-token"}


class ToVendorTests(TestCase):
    @patch(
        "basket.news.backends.ctms.newsletter_slugs", return_value=["mozilla-welcome"]
    )
    def test_sample_format(self, mock_nl_slugs):
        """The output of from_vendor is a valid input to to_vendor"""
        data = to_vendor(SAMPLE_BASKET_FORMAT)
        assert data == {
            "amo": {
                "display_name": "Add-ons Author",
                "last_login": "2021-01-28",
                "location": "California",
                "profile_url": "firefox/user/98765",
                "user": True,
                "user_id": "98765",
            },
            "email": {
                "basket_token": "c4a7d759-bb52-457b-896b-90f1d3ef8433",
                "create_timestamp": "2020-03-28T15:41:00.000Z",
                "double_opt_in": True,
                "email_format": "H",
                "email_id": "332de237-cab7-4461-bcc3-48e68f42bd5c",
                "email_lang": "en",
                "first_name": "Jane",
                "has_opted_out_of_email": False,
                "last_name": "Doe",
                "mailing_country": "us",
                "primary_email": "contact@example.com",
                "sfdc_id": "001A000023aABcDEFG",
                "unsubscribe_reason": "string",
                "update_timestamp": "2021-01-28T21:26:57.511Z",
            },
            "fxa": {
                "account_deleted": False,
                "created_date": "2021-01-29T18:43:49.082375+00:00",
                "first_service": "sync",
                "fxa_id": "6eb6ed6ac3b64259968aa490c6c0b9df",
                "lang": "en,en-US",
                "primary_email": "my-fxa-acct@example.com",
            },
            "newsletters": [{"name": "mozilla-welcome", "subscribed": True}],
            "vpn_waitlist": {"geo": "fr", "platform": "ios,mac"},
        }

    def test_country(self):
        """country is validated and added as email.mailing_country"""
        tests = (
            ("mx", "mx"),
            ("CN", "cn"),
            (" USA ", "us"),
            ("en", None),
            (" ABC ", None),
        )

        for original, converted in tests:
            data = to_vendor({"country": original})
            if converted:
                assert data == {"email": {"mailing_country": converted}}
            else:
                assert data == {}

    @override_settings(EXTRA_SUPPORTED_LANGS=["zh-hans", "zh-hant"])
    @patch(
        "basket.news.newsletters.newsletter_languages",
        return_value=["de", "en", "es", "fr", "zh-TW"],
    )
    def test_lang(self, mock_languages):
        """lang is validated and added as email.email_lang"""
        tests = (
            ("en", "en"),
            ("ES", "es"),
            ("  FR  ", "fr"),
            ("en-US", "en"),
            ("zh", "zh"),
            ("zh-TW ", "zh"),
            (" zh-CN", "zh"),
            ("zh-Hans ", "zh-Hans"),
            ("zh-Hant", "zh-Hant"),
            (" ru", "en"),
            ("en-CA", "en"),
            ("es-MX", "es"),
        )
        for original, converted in tests:
            data = to_vendor({"lang": original})
            if converted:
                assert data == {"email": {"email_lang": converted}}
            else:
                assert data == {}

    def test_truncate(self):
        """Strings are stripped and truncated."""
        tests = (
            ("first_name", 255, "email", "first_name", f" first {'x' * 500}"),
            ("last_name", 255, "email", "last_name", f" Last {'x' * 500} "),
            ("reason", 1000, "email", "unsubscribe_reason", f"Cause:{'.' * 1500}"),
            ("fpn_country", 100, "vpn_waitlist", "geo", f" Iran {'a' * 100} "),
            ("fpn_platform", 100, "vpn_waitlist", "platform", f" Linux {'x' * 120} "),
        )

        for field, max_length, group, key, value in tests:
            assert len(value) > max_length
            data = to_vendor({field: value})
            new_value = data[group][key]
            assert len(new_value) == max_length

    def test_truncate_empty_to_none(self):
        """Empty or space-only strings are omitted."""

        data = {
            "email": "",
            "format": "\n",
            "first_name": "\r\n",
            "last_name": "\t",
            "reason": " " * 1200,
            "fpn_country": " ",
            "fpn_platform": None,
        }
        prepared = to_vendor(data)
        assert prepared == {}

    @patch(
        "basket.news.backends.ctms.newsletter_slugs",
        return_value=["slug1", "slug2", "slug3", "slug4"],
    )
    def test_newsletter_list(self, mock_nl_slugs):
        """A newsletter list is treated as subscription requests."""
        data = {"newsletters": ["slug1", "slug2", "slug3", "other"]}
        prepared = to_vendor(data)
        assert prepared == {
            "newsletters": [
                {"name": "slug1", "subscribed": True},
                {"name": "slug2", "subscribed": True},
                {"name": "slug3", "subscribed": True},
            ]
        }

    @patch(
        "basket.news.backends.ctms.newsletter_slugs",
        return_value=["slug1", "slug2", "slug3", "slug4"],
    )
    def test_newsletter_map(self, mock_nl_slugs):
        """A newsletter map combines subscribe and unsubscribe requests."""
        data = {
            "newsletters": {
                "slug1": True,
                "slug2": False,
                "slug3": True,
                "other": True,
            }
        }
        prepared = to_vendor(data)
        assert prepared == {
            "newsletters": [
                {"name": "slug1", "subscribed": True},
                {"name": "slug2", "subscribed": False},
                {"name": "slug3", "subscribed": True},
            ]
        }

    def test_ignored_fields(self):
        """Some fields exported to SFDC are quietly ignored in CTMS."""
        data = {
            "_set_subscriber": True,
            "record_type": "someRecordType",
            "postal_code": "90210",
            "source_url": "https://example.com",
            "fsa_school": "U of X",
            "fsa_grad_year": "2020",
            "fsa_major": "CS",
            "fsa_city": "San Francisco",
            "fsa_current_status": "Graduate",
            "fsa_allow_share": True,
            "cv_days_interval": 2,
            "cv_created_at": "2021-03-11",
            "cv_goal_reached_at": "2021-04-11",
            "cv_first_contribution_date": "2021-03-12",
            "cv_two_day_streak": True,
            "cv_last_active_date": "2021-04-11",
            "amo_deleted": True,
            "fxa_last_login": "2020-04-11",
        }
        prepared = to_vendor(data)
        assert prepared == {}

    def test_unknown_field_raises(self):
        """An unknown basket field is an exception."""
        data = {"foo": "bar"}
        self.assertRaises(KeyError, to_vendor, data)


class CTMSSessionTests(TestCase):

    EXAMPLE_TOKEN = {
        "access_token": "a.long.base64.string",
        "token_type": "bearer",
        "expires_in": 3600,
        "expires_at": 1617144323.2891595,
    }

    @patch("basket.news.backends.ctms.cache", spec_set=("get", "set"))
    @patch("basket.news.backends.ctms.OAuth2Session")
    def test_get_with_new_auth(self, mock_oauth2_session, mock_cache):
        """An OAuth2 token is fetched if needed."""
        mock_session = Mock(
            spec_set=(
                "authorized",
                "fetch_token",
                "request",
                "register_compliance_hook",
            )
        )
        mock_session.authorized = False
        mock_session.fetch_token.return_value = self.EXAMPLE_TOKEN
        mock_response = Mock(spec_set=("status_code",))
        mock_response.status_code = 200
        mock_session.request.return_value = mock_response
        mock_oauth2_session.return_value = mock_session
        mock_cache.get.return_value = None

        session = CTMSSession("https://ctms.example.com", "id", "secret")
        resp = session.get("/ctms", params={"primary_email": "test@example.com"})
        assert resp == mock_response

        mock_oauth2_session.assert_called_once_with(client=ANY, token=None)
        mock_session.register_compliance_hook.assert_called_once()
        mock_cache.get.assert_called_once_with("ctms_token")
        mock_session.fetch_token.assert_called_once_with(
            client_id="id",
            client_secret="secret",
            token_url="https://ctms.example.com/token",
        )
        mock_cache.set.assert_called_once_with(
            "ctms_token", self.EXAMPLE_TOKEN, timeout=3420
        )
        mock_session.request.assert_called_once_with(
            "GET",
            "https://ctms.example.com/ctms",
            params={"primary_email": "test@example.com"},
        )

    @patch("basket.news.backends.ctms.cache", spec_set=("get",))
    @patch("basket.news.backends.ctms.OAuth2Session")
    def test_get_with_existing_auth(self, mock_oauth2_session, mock_cache):
        """An existing OAuth2 token is reused without calling fetch_token."""
        mock_session = Mock(
            spec_set=("authorized", "request", "register_compliance_hook")
        )
        mock_session.authorized = True
        mock_response = Mock(spec_set=("status_code",))
        mock_response.status_code = 200
        mock_session.request.return_value = mock_response
        mock_oauth2_session.return_value = mock_session
        mock_cache.get.return_value = self.EXAMPLE_TOKEN

        session = CTMSSession("https://ctms.example.com", "id", "secret")
        resp = session.get("/ctms", params={"primary_email": "test@example.com"})
        assert resp == mock_response

        mock_oauth2_session.assert_called_once_with(
            client=ANY, token=self.EXAMPLE_TOKEN
        )
        mock_session.register_compliance_hook.assert_called_once()
        mock_cache.get.assert_called_once_with("ctms_token")
        mock_session.request.assert_called_once_with(
            "GET",
            "https://ctms.example.com/ctms",
            params={"primary_email": "test@example.com"},
        )

    @patch("basket.news.backends.ctms.cache", spec_set=("get", "set"))
    @patch("basket.news.backends.ctms.OAuth2Session")
    def test_get_with_re_auth(self, mock_oauth2_session, mock_cache):
        """A new OAuth2 token is fetched on an auth error."""
        mock_session = Mock(
            spec_set=(
                "authorized",
                "fetch_token",
                "request",
                "register_compliance_hook",
            )
        )
        mock_session.authorized = True
        new_token = {
            "access_token": "a.different.base64.string",
            "token_type": "bearer",
            "expires_in": 7200,
            "expires_at": 161715000.999,
        }
        mock_session.fetch_token.return_value = new_token
        mock_response_1 = Mock(spec_set=("status_code",))
        mock_response_1.status_code = 401
        mock_response_2 = Mock(spec_set=("status_code",))
        mock_response_2.status_code = 200
        mock_session.request.side_effect = [mock_response_1, mock_response_2]
        mock_oauth2_session.return_value = mock_session
        mock_cache.get.return_value = self.EXAMPLE_TOKEN

        session = CTMSSession("https://ctms.example.com", "id", "secret")
        resp = session.get("/ctms", params={"primary_email": "test@example.com"})
        assert resp == mock_response_2

        mock_oauth2_session.assert_called_once_with(
            client=ANY, token=self.EXAMPLE_TOKEN
        )
        mock_session.register_compliance_hook.assert_called_once()
        mock_cache.get.assert_called_once_with("ctms_token")
        mock_session.fetch_token.assert_called_once_with(
            client_id="id",
            client_secret="secret",
            token_url="https://ctms.example.com/token",
        )
        mock_cache.set.assert_called_once_with("ctms_token", new_token, timeout=6840)
        mock_session.request.assert_called_with(
            "GET",
            "https://ctms.example.com/ctms",
            params={"primary_email": "test@example.com"},
        )
        assert mock_session.request.call_count == 2

    @patch("basket.news.backends.ctms.cache", spec_set=("get",))
    @patch("basket.news.backends.ctms.OAuth2Session")
    def test_get_with_failed_auth(self, mock_oauth2_session, mock_cache):
        """A new OAuth2 token is fetched on an auth error."""
        mock_session = Mock(
            spec_set=("authorized", "fetch_token", "register_compliance_hook")
        )
        mock_session.authorized = False
        err_resp = Response()
        err_resp.status_code = 400
        err_resp._content = json.dumps({"detail": "Incorrect username or password"})
        err = HTTPError(response=err_resp)
        mock_session.fetch_token.side_effect = err
        mock_oauth2_session.return_value = mock_session
        mock_cache.get.return_value = None

        session = CTMSSession("https://ctms.example.com", "id", "secret")
        with self.assertRaises(HTTPError) as context:
            session.get("/ctms", params={"primary_email": "test@example.com"})
        assert context.exception == err

        mock_oauth2_session.assert_called_once_with(client=ANY, token=None)
        mock_session.register_compliance_hook.assert_called_once()
        mock_cache.get.assert_called_once_with("ctms_token")
        mock_session.fetch_token.assert_called_once_with(
            client_id="id",
            client_secret="secret",
            token_url="https://ctms.example.com/token",
        )

    def test_init_bad_parameter(self):
        """CTMSSession() fails if parameters are bad."""

        params = {
            "api_url": "http://ctms.example.com",
            "client_id": "id",
            "client_secret": "secret",
        }
        CTMSSession(**params)  # Doesn't raise

        bad_param_values = {
            "api_url": ("/ctms", "ctms.example.com", "https://"),
            "client_id": ("",),
            "client_secret": ("",),
            "token_cache_key": ("",),
        }
        for key, values in bad_param_values.items():
            for value in values:
                bad_params = params.copy()
                bad_params[key] = value
                with self.assertRaises(ValueError):
                    CTMSSession(**bad_params)

    def test_init_long_api_url(self):
        """CTMSSession() uses protocol and netloc of api_url."""

        session = CTMSSession(
            "https://ctms.example.com/docs?refresh=1", "client_id", "client_secret"
        )
        assert session.api_url == "https://ctms.example.com"

    @override_settings(
        CTMS_ENABLED=True,
        CTMS_URL="https://ctms.example.com",
        CTMS_CLIENT_ID="client_id",
        CTMS_CLIENT_SECRET="client_secret",
    )
    def test_ctms_session_enabled(self):
        """ctms_session() returns a CTMSSession from Django settings"""
        session = ctms_session()
        assert session.api_url == "https://ctms.example.com"

    @override_settings(CTMS_ENABLED=False)
    def test_ctms_session_disabled(self):
        """ctms_session() returns None when CTMS_ENABLED=False"""
        session = ctms_session()
        assert session is None


def mock_interface(expected_call, status_code, response_data, reason=None):
    """Return a CTMSInterface with a mocked session and response"""
    call = expected_call.lower()
    assert call in set(("patch", "post", "put", "get"))
    session = Mock(spec_set=[call])
    caller = getattr(session, call)

    def set_request(path, **kwargs):
        url = f"https://ctms.example.com{path}"
        request = Request(expected_call, url, **kwargs)
        response.request = request.prepare()
        response.url = url
        return DEFAULT

    caller.side_effect = set_request

    response = Response()
    response.status_code = status_code
    if reason:
        response.reason = reason
    else:
        reasons = {200: "OK", 422: "Unprocessable Entity"}
        response.reason = reasons.get(status_code, "Unknown")
    response._content = json.dumps(response_data).encode("utf8")

    getattr(session, call).return_value = response

    return CTMSInterface(session)


class MockInterfaceTests(TestCase):
    def test_post_to_create_success(self):
        expected = {
            "email": {
                "primary_email": "test@example.com",
                "email_id": str(uuid4()),
                "other": "stuff",
            },
            "other_groups": {"more": "data"},
        }
        interface = mock_interface("POST", 200, expected)
        resp = interface.post_to_create(
            {"email": {"primary_email": "test@example.com"}}
        )
        assert resp == expected

    def test_post_to_create_data_failure(self):
        expected = {
            "detail": [
                {
                    "loc": ["body", "email"],
                    "msg": "field required",
                    "type": "value_error.missing",
                }
            ]
        }
        interface = mock_interface("POST", 422, expected)
        with self.assertRaises(HTTPError) as context:
            interface.post_to_create({})
        error = context.exception
        assert error.response.status_code == 422
        assert error.response.json() == expected

    def test_post_to_create_auth_failure(self):
        expected = {"detail": "Incorrect username or password"}
        interface = mock_interface("POST", 400, expected)
        with self.assertRaises(HTTPError) as context:
            interface.post_to_create({"email": {"primary_email": "test@example.com"}})
        error = context.exception
        assert error.response.status_code == 400
        assert error.response.json() == expected


class CTMSTests(TestCase):

    TEST_CTMS_CONTACT = {
        "amo": {"user_id": "amo-id"},
        "email": {
            "email_id": "a-ctms-uuid",
            "basket_token": "token",
            "primary_email": "basket@example.com",
            "sfdc_id": "sfdc-id",
        },
        "fxa": {"fxa_id": "fxa-id"},
        "mofo": {
            "mofo_email_id": "mofo-email-id",
            "mofo_contact_id": "mofo-contact-id",
        },
    }
    TEST_BASKET_FORMAT = {
        "amo_id": "amo-id",
        "email_id": "a-ctms-uuid",
        "email": "basket@example.com",
        "fxa_id": "fxa-id",
        "id": "sfdc-id",
        "token": "token",
    }

    def test_get_no_interface(self):
        """If the interface is None (disabled or other issue), None is returned."""
        ctms = CTMS(None)
        assert ctms.get(token="token") is None

    def test_get_by_email_id(self):
        """If email_id is passed, GET /ctms/{email_id} is called."""
        email_id = self.TEST_CTMS_CONTACT["email"]["email_id"]
        interface = mock_interface("GET", 200, self.TEST_CTMS_CONTACT)
        ctms = CTMS(interface)
        user_data = ctms.get(email_id=email_id)
        assert user_data == self.TEST_BASKET_FORMAT
        interface.session.get.assert_called_once_with("/ctms/a-ctms-uuid")

    def test_get_by_email_id_not_found(self):
        """If a contact is not found by email_id, an exception is raised."""
        ctms = CTMS(mock_interface("GET", 404, {"detail": "Unknown contact_id"}))
        with self.assertRaises(HTTPError) as context:
            ctms.get(email_id="unknown-id")
        assert context.exception.response.status_code == 404

    def test_get_by_token(self):
        """If token is passed, GET /ctms?basket_token={token} is called."""
        token = self.TEST_CTMS_CONTACT["email"]["basket_token"]
        interface = mock_interface("GET", 200, [self.TEST_CTMS_CONTACT])
        ctms = CTMS(interface)
        user_data = ctms.get(token=token)
        assert user_data == self.TEST_BASKET_FORMAT
        interface.session.get.assert_called_once_with(
            "/ctms", params={"basket_token": token}
        )

    def test_get_by_token_not_found(self):
        """If a contact is not found by token, None is returned."""
        ctms = CTMS(mock_interface("GET", 200, []))
        assert ctms.get(token="unknown-token") is None

    def test_get_by_email(self):
        """If email is passed, GET /ctms?primary_email={email} is called."""
        email = self.TEST_CTMS_CONTACT["email"]["primary_email"]
        interface = mock_interface("GET", 200, [self.TEST_CTMS_CONTACT])
        ctms = CTMS(interface)
        user_data = ctms.get(email=email)
        assert user_data == self.TEST_BASKET_FORMAT
        interface.session.get.assert_called_once_with(
            "/ctms", params={"primary_email": email}
        )

    def test_get_by_sfdc_id(self):
        """If sfdc_id is passed, GET /ctms?sfdc_id={id} is called."""
        sfdc_id = self.TEST_CTMS_CONTACT["email"]["sfdc_id"]
        interface = mock_interface("GET", 200, [self.TEST_CTMS_CONTACT])
        ctms = CTMS(interface)
        user_data = ctms.get(sfdc_id=sfdc_id)
        assert user_data == self.TEST_BASKET_FORMAT
        interface.session.get.assert_called_once_with(
            "/ctms", params={"sfdc_id": sfdc_id}
        )

    def test_get_by_fxa_id(self):
        """If fxa_id is passed, GET /ctms?fxa_id={fxa_id} is called."""
        fxa_id = self.TEST_CTMS_CONTACT["fxa"]["fxa_id"]
        interface = mock_interface("GET", 200, [self.TEST_CTMS_CONTACT])
        ctms = CTMS(interface)
        user_data = ctms.get(fxa_id=fxa_id)
        assert user_data == self.TEST_BASKET_FORMAT
        interface.session.get.assert_called_once_with(
            "/ctms", params={"fxa_id": fxa_id}
        )

    def test_get_by_mofo_email_id(self):
        """If mofo_email_id is passed, GET /ctms?mofo_email_id={mofo_email_id} is called."""
        mofo_email_id = self.TEST_CTMS_CONTACT["mofo"]["mofo_email_id"]
        interface = mock_interface("GET", 200, [self.TEST_CTMS_CONTACT])
        ctms = CTMS(interface)
        user_data = ctms.get(mofo_email_id=mofo_email_id)
        assert user_data == self.TEST_BASKET_FORMAT
        interface.session.get.assert_called_once_with(
            "/ctms", params={"mofo_email_id": mofo_email_id}
        )

    def test_get_by_amo_id(self):
        """If amo_id is passed, GET /ctms?amo_id={amo_id} is called."""
        amo_id = self.TEST_CTMS_CONTACT["amo"]["user_id"]
        interface = mock_interface("GET", 200, [self.TEST_CTMS_CONTACT])
        ctms = CTMS(interface)
        user_data = ctms.get(amo_id=amo_id)
        assert user_data == self.TEST_BASKET_FORMAT
        interface.session.get.assert_called_once_with(
            "/ctms", params={"amo_user_id": amo_id}
        )

    def test_get_by_several_ids(self):
        """If if multiple IDs are passed, the best is used."""
        email_id = self.TEST_CTMS_CONTACT["email"]["email_id"]
        interface = mock_interface("GET", 200, self.TEST_CTMS_CONTACT)
        ctms = CTMS(interface)
        user_data = ctms.get(
            email_id=email_id, token="some-token", email="some-email@example.com"
        )
        assert user_data == self.TEST_BASKET_FORMAT
        interface.session.get.assert_called_once_with(f"/ctms/{email_id}")

    def test_get_by_amo_id_multiple_contacts(self):
        """If an ID returns mutliple contacts, a RuntimeError is raised."""
        amo_id = self.TEST_CTMS_CONTACT["amo"]["user_id"]
        contact2 = {
            "amo": {"user_id": "amo-user-id"},
            "email": {
                "email_id": "a-ctms-uuid",
                "basket_token": "token",
                "primary_email": "basket@example.com",
                "sfdc_id": "sfdc-id",
            },
            "fxa": {"fxa_id": "fxa-id"},
            "mofo": {
                "mofo_email_id": "mofo-email-id",
                "mofo_contact_id": "mofo-contact-id",
            },
        }
        ctms = CTMS(mock_interface("GET", 200, [self.TEST_CTMS_CONTACT, contact2]))
        self.assertRaises(RuntimeError, ctms.get, amo_id=amo_id)

    def test_get_no_ids(self):
        """RuntimeError is raised if all IDs are None."""
        ctms = CTMS("interface should not be called")
        self.assertRaises(RuntimeError, ctms.get, token=None)
