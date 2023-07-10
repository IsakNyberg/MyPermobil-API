"""Permobil API."""

import asyncio
import datetime
import re

import aiohttp
from aiocache import Cache

from .const import (
    ENDPOINT_APPLICATIONAUTHENTICATIONS,
    ENDPOINT_APPLICATIONLINKS,
    ENDPOINT_LOOKUP,
    ITEM_LOOKUP,
    GET_REGIONS,
    EMAIL_REGEX,
)


class MyPermobilException(Exception):
    """Permobil Exception. Generic Permobil Exception."""


class MyPermobilAPIException(MyPermobilException):
    """Permobil Exception. Exception raised when the API returns an error."""


class MyPermobilConnectionException(MyPermobilException):
    """Permobil Exception. Exception raised when the AIOHTTP."""


class MyPermobilClientException(MyPermobilException):
    """Permobil Exception. Exception raised when the Client is used incorrectly."""


CACHE: Cache = Cache()
CACHE_TTL = 5 * 60  # 5 minutes
CACHE_ERROR_TTL = 10  # 10 seconds
CACHE_LOCKS = {}


async def async_get_cache(key):
    """Get cache."""
    # get the cached data
    res = await CACHE.get(key)
    if isinstance(res, Exception):
        # if the cached data is an error, raise instead of returning
        raise res
    return res


def cacheable(func):
    """Decorator to cache function calls for methods that
    fetch multiple data points from the API.
    """

    async def wrapper(*args, **kwargs):
        """wrapper."""
        key = func.__name__ + str(args) + str(kwargs)
        # check if the request is already cached
        cached_data = await async_get_cache(key)
        if cached_data:
            # return cached data
            return cached_data

        # check if the request is already in progress
        if key in CACHE_LOCKS:
            # request is already in progress, wait for it to finish
            await CACHE_LOCKS[key].wait()
            res = await async_get_cache(key)
            return res  # return cached data once it has finished by other task

        # start request it and lock other requests from starting
        CACHE_LOCKS[key] = asyncio.Event()

        try:
            response = await func(*args, **kwargs)  # make the request
            await CACHE.set(key, response, ttl=CACHE_TTL)  # cache the response
        except Exception as err:  # pylint: disable=broad-except
            # if there is an error, cache the error and raise it
            await CACHE.set(key, err, ttl=CACHE_ERROR_TTL)
            raise err
        finally:
            # regardless of the outcome, unlock other threads
            CACHE_LOCKS[key].set()
            del CACHE_LOCKS[key]
        return response

    return wrapper


def validate_email(email: str) -> str:
    """Validates an email."""
    if not email:
        raise MyPermobilClientException("Missing email")
    if not re.match(EMAIL_REGEX, email):
        raise MyPermobilClientException("Invalid email")
    return email


def validate_code(code: str) -> str:
    """Validates an code."""
    if not code:
        raise MyPermobilClientException("Missing code")
    if not code.isdigit():
        raise MyPermobilClientException("Code must be a number")
    if len(code) != 6:
        raise MyPermobilClientException("Code must be 6 digits long")
    return code


def validate_token(token: str) -> str:
    """Validates an token."""
    if not token:
        raise MyPermobilClientException("Missing token")
    if len(token) != 256:
        # the token must be 256 characters long
        raise MyPermobilClientException("Invalid token")
    return token


def validate_expiration_date(expiration_date: str) -> str:
    """Validates an expiration date, both format and value."""
    if not expiration_date:
        raise MyPermobilClientException("Missing expiration date")
    date = None
    try:
        date = datetime.datetime.strptime(expiration_date, "%Y-%m-%d")
    except ValueError as err:
        raise MyPermobilClientException("Invalid expiration date") from err
    # check if the expiration date is in the future
    if date < datetime.datetime.now():
        raise MyPermobilClientException("Expired token")
    return expiration_date


def validate_region(region: str) -> str:
    """Validates an region."""
    if not region:
        raise MyPermobilClientException("Missing region")
    if not region.startswith("https://") and not region.startswith("http://"):
        raise MyPermobilClientException("Region missing protocol")
    return region


async def create_session():
    """Create a client session."""
    return aiohttp.ClientSession()


class MyPermobil:
    """Permobil API."""

    def __init__(
        self,
        application: str,
        session: aiohttp.ClientSession,
        email: str = None,
        region: str = None,
        code: str = None,
        token: str = None,
        expiration_date: str = None,
        request_timeout: int = 10,
    ) -> None:
        """Initialize."""
        self.application = application
        self.session = session
        self.email = email
        self.region = region
        self.code = code
        self.token = token
        self.expiration_date = expiration_date
        self.request_timeout = request_timeout

        self.authenticated = False

    # Magic methods
    def __str__(self) -> str:
        """str."""
        app, email, region = self.application, self.email, self.region
        code, token, exp = self.code, self.token, self.expiration_date
        return f"Permobil({app}, {email}, {region}, {code}, {token}, {exp})"

    # Selectors
    @property
    def headers(self):
        """headers."""
        if not self.authenticated:
            raise MyPermobilClientException("Not authenticated")
        return {"Authorization": f"Bearer {self.token}"}

    def set_email(self, email: str):
        """Set email."""
        if self.authenticated:
            raise MyPermobilClientException("Cannot change email after authentication")
        self.email = validate_email(email)

    def set_region(self, region: str):
        """Set region."""
        if self.authenticated:
            raise MyPermobilClientException("Cannot change region after authentication")
        self.region = validate_region(region)

    def set_code(self, code: int):
        """Set code."""
        if self.authenticated:
            raise MyPermobilClientException("Cannot change code after authentication")
        self.code = validate_code(code)

    def set_token(self, token: str):
        """Set token."""
        if self.authenticated:
            raise MyPermobilClientException("Cannot change token after authentication")
        self.token = validate_token(token)

    def set_expiration_date(self, expiration_date: str):
        """Set expiration date."""
        if self.authenticated:
            raise MyPermobilClientException("Cannot change date after authentication")
        self.expiration_date = validate_expiration_date(expiration_date)

    def set_application(self, application: str):
        """Set application."""
        if self.authenticated:
            raise MyPermobilClientException("Cannot change app after authentication")
        self.application = application

    async def close_session(self):
        """Close session."""
        if self.session is None:
            raise MyPermobilClientException("Session does not exist")
        await self.session.close()
        self.session = None

    def self_authenticate(self):
        """authenticate. Manually set token and expiration date."""
        if self.authenticated:
            raise MyPermobilClientException("Already authenticated")
        if not self.application:
            raise MyPermobilClientException("Missing application name")
        validate_region(self.region)
        validate_email(self.email)
        validate_token(self.token)
        validate_expiration_date(self.expiration_date)
        self.authenticated = True

    def deauthenticate(self):
        """deauthenticate."""
        if not self.authenticated:
            raise MyPermobilClientException("Not authenticated")
        # TODO send deauthentication request

    # API Methods
    async def get_request(self, *args, **kwargs):
        """Get request."""
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.request_timeout
        if "headers" not in kwargs and self.authenticated:
            kwargs["headers"] = self.headers

        try:
            return await self.session.get(*args, **kwargs)
        except aiohttp.ClientConnectorError as err:
            raise MyPermobilConnectionException("Connection error") from err
        except asyncio.TimeoutError as err:
            raise MyPermobilConnectionException("Connection timeout") from err
        except aiohttp.ClientError as err:
            raise MyPermobilConnectionException("Client error") from err
        except Exception as err:
            raise MyPermobilAPIException("Unknown error") from err

    async def post_request(self, *args, **kwargs):
        """Post request."""
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.request_timeout
        if "headers" not in kwargs and self.authenticated:
            kwargs["headers"] = self.headers

        try:
            return await self.session.post(*args, **kwargs)
        except aiohttp.ClientConnectorError as err:
            raise MyPermobilConnectionException("Connection error") from err
        except asyncio.TimeoutError as err:
            raise MyPermobilConnectionException("Connection timeout") from err
        except aiohttp.ClientError as err:
            raise MyPermobilConnectionException("Client error") from err
        except Exception as err:
            raise MyPermobilAPIException("Unknown error") from err

    @cacheable
    async def request_regions(
        self, include_icons: bool = False, include_internal: bool = False
    ):
        """Get regions."""
        response = await self.get_request(GET_REGIONS, headers={})
        if response.status == 200:
            response_json = await response.json()
            regions = {}
            for region in response_json:
                if not include_internal:
                    if (
                        region.get("backendPort") != 443
                        or region.get("serverType") != "Production"
                    ):
                        continue
                region_id = region.get("_id")
                regions[region_id] = {}
                regions[region_id]["name"] = region.get("name")
                regions[region_id]["port"] = region.get("backendPort")
                protocol = "https" if region.get("backendPort") == 443 else "http"
                regions[region_id]["url"] = f"{protocol}://{region.get('host')}"
                if include_icons:
                    regions[region_id]["icon"] = region.get("flag")
            return regions

        if response.status in (404, 500):
            text = await response.text()
            raise MyPermobilAPIException(text)

    async def request_region_names(self, include_internal: bool = False):
        """Get region names."""
        regions = await self.request_regions(
            include_icons=False, include_internal=include_internal
        )
        return {
            regions[region_id].get("name"): regions[region_id].get("url")
            for region_id in regions
        }

    async def request_application_code(
        self, email: str = None, region: str = None, application: str = None
    ):
        """Post application link."""
        if email is None:
            email = self.email
        if region is None:
            region = self.region
        if application is None:
            application = self.application

        if self.authenticated:
            raise MyPermobilClientException("Already authenticated")
        if not application:
            raise MyPermobilClientException("Missing application name")
        email = validate_email(email)
        region = validate_region(region)

        url = region + ENDPOINT_APPLICATIONLINKS
        json = {"username": email, "application": application}
        response = await self.post_request(url, json=json)
        if response.status != 204:
            text = await response.text()
            raise MyPermobilAPIException(text)

    async def request_application_token(
        self,
        email: str = None,
        code: int = None,
        region: str = None,
        application: str = None,
        expiration_date: str = None,
    ) -> str:
        """Post the application token."""
        if email is None:
            email = self.email
        if code is None:
            code = self.code
        if region is None:
            region = self.region
        if application is None:
            application = self.application

        if self.authenticated:
            raise MyPermobilClientException("Already authenticated")
        email = validate_email(email)
        region = validate_region(region)
        code = validate_code(code)

        url = region + ENDPOINT_APPLICATIONAUTHENTICATIONS
        json = {
            "username": email,
            "code": code,
            "application": application,
            "expirationDate": expiration_date,
        }
        response = await self.post_request(url, json=json)

        if response.status == 200:
            json = await response.json()
            token = json.get("token")
            if expiration_date is None:
                # set expiration date to 1 year from now
                time_delta = datetime.timedelta(days=365)
                date = datetime.datetime.now() + time_delta
                expiration_date = date.strftime("%Y-%m-%d")

        elif response.status == 401:
            raise MyPermobilAPIException("Email not registered for region")
        elif response.status == 403:
            raise MyPermobilAPIException("Incorrect code")
        elif response.status in (400, 500):
            resp = await response.json()
            raise MyPermobilAPIException(resp.get("error", resp))
        else:
            text = await response.text()
            raise MyPermobilAPIException(text)

        return token, expiration_date

    async def request_item(
        self, item: str, endpoint: str = None, headers: dict = None
    ) -> str | int | float | bool | dict | list:
        """Takes and item, finds the endpoint and makes the request."""
        if headers is None:
            headers = self.headers

        if endpoint not in ENDPOINT_LOOKUP:
            if endpoint is None:
                endpoint = ENDPOINT_LOOKUP.get(item)
            else:
                raise MyPermobilClientException(f"Invalid endpoint {endpoint}")
            if endpoint is None:
                raise MyPermobilClientException(f"No endpoint for item: {item}")

        if item not in ITEM_LOOKUP[endpoint]:
            raise MyPermobilClientException(f"{item} not in endpoint {endpoint}")

        response = await self.request_endpoint(endpoint, headers)
        return response.get(item)

    @cacheable
    async def request_endpoint(self, endpoint: str, headers: dict = None) -> dict:
        """Makes a request to an endpoint."""
        if headers is None:
            headers = self.headers

        resp = await self.get_request(self.region + endpoint)
        status = resp.status
        json = await resp.json()
        if status >= 200 and status < 300:
            return json

        text = await resp.text()
        msg = json.get("error", text)
        raise MyPermobilAPIException(f"Permobil API {status}: {msg}")
