from newsroom.core.i18n import TextDirection
from newsroom.core.schemas import Schema


class LocaleOut(Schema):
    code: str
    name: str
    native_name: str
    direction: TextDirection
    is_default: bool
