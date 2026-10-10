"""Validate only report data crossing a persistence boundary."""
import re
from urllib.parse import unquote, urlsplit

# Hodor path tokens are 32 hexadecimal characters, including tokens discovered
# in navigation that are not part of the bootstrap secret registry.
HODOR_TOKEN = re.compile(r'[a-fA-F0-9]{32}')


def validate_persistent_data(value: object, secrets: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in {'passid', 'passtoken', 'tokenpass', 'xx-profile-id'}:
                raise ValueError('Authentication data cannot be persisted')
            validate_persistent_data(child, secrets)
    elif isinstance(value, (list, tuple)):
        for child in value:
            validate_persistent_data(child, secrets)
    elif isinstance(value, str):
        decoded = unquote(value)
        if (HODOR_TOKEN.search(decoded) or 'hodor.canalplus.pro' in decoded.casefold()
                or any(secret and (secret in value or secret in decoded) for secret in secrets)):
            raise ValueError('Authentication data cannot be persisted')


def validate_public_url(value: str) -> None:
    if not value:
        return
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or parsed.netloc != 'www.canalplus.com'
                or not parsed.path.startswith('/') or parsed.path.startswith('//')
                or parsed.query or parsed.fragment
                or any(c.isspace() or ord(c) < 32 or c == '\\' for c in unquote(value))):
            raise ValueError
    except ValueError:
        raise ValueError('Invalid public myCANAL URL') from None
    validate_persistent_data(value)


def public_url(path: str) -> str:
    if not path.startswith('/') or path.startswith('//'):
        return ''
    value = 'https://www.canalplus.com' + path
    try:
        validate_public_url(value)
    except ValueError:
        return ''
    return value
