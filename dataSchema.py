#
# scheduLight - automation tool for BigBlueButton and Greenlight
# copyright Martin Thomas Schrott 2020
#
# This file is part of scheduLight
# scheduLight is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
# You should have received a copy of the GNU General Public License along with Foobar.  If not, see <https://www.gnu.org/licenses/>.
#
import re
from marshmallow import Schema, fields, INCLUDE, post_load, validates, ValidationError
from schema import Schema as dictSchema
from schema import And, Use, Optional, Regex, SchemaError
from datetime import datetime

def validate_schema(self, conf_schema, conf):
    try:
        conf_schema.validate(conf)
        return
    except SchemaError as ERR:
        return ERR.code

def is_email(email):
    if re.match(r'[^@]+@[^@]+\.[^@]+', email):
        return True
    else:
        raise Exception()

class ownerSchema(Schema):
    """ /api/meetings post

    Parameters:
     - email (email)
     - fullName (str)
    """
    email = fields.Email(required=True)
    fullName = fields.Str(required=True, error_messages={"required": "please specify the full name of the owner."})

    class Meta:
        unknown = INCLUDE

    @post_load
    def lowerstrip_email(self, item, **kwargs):
        item['email'] = item['email'].lower().strip()
        return item

class meetingSchema(Schema):
    """ /api/meetings post

    Parameters:
     - meetingName (str)
     - id (str)
     - server (str)
     - owner (dict)
    """
    meetingName = fields.Str(required=True)
    id = fields.Str(required=True, error_messages={"required": "please specify an id for the meeting."})
    server = fields.Str(required=True, error_messages={"required": "please specify a target server for the meeting."})
    owner = fields.Nested(ownerSchema)
    startDate = fields.DateTime(required=False)

    @validates('startDate')
    def is_in_future(self, value):
        """'value' is the datetime parsed from startDate by marshmallow"""
        now = datetime.now()
        if value < now:
            raise ValidationError("startDate has to be in future!")

    class Meta:
        unknown = INCLUDE

class serverSchema(Schema):
    """ /api/servers post

    Parameters:
        - id(str)
        - BBB_SECRET (str)
        - BBB_URL (url)
        - link_base (url)
        - mailDebug (bool)
        - send_emails (bool)
        - mailFrom (email)
        - mailFromName (str)
        - mailPassword (str)
        - mailServer (Str)
        - mailUser (str)
    """
    id = fields.Str(required=True)
    BBB_SECRET = fields.Str(required=True)
    BBB_URL = fields.Url(required=True, error_messages={"required": "please specify the bbb server url e.g. https://your_bbb_server_url/bigbluebutton/api"})
    link_base = fields.Url(required=True, error_messages={"required": "please specify a base url for greenlight. e.g. https://your_greenlight_url/b"})
    mailDebug = fields.Bool(required=False)
    send_emails = fields.Bool(required=False)
    mailTo = fields.Email(required=False)
    mailToName = fields.Str(required=False)
    mailFrom = fields.Email(required=True)
    mailFromName = fields.Str(required=True)
    mailPassword = fields.Str(required=True)
    mailServer = fields.Str(required=True)
    mailUser = fields.Str(required=True)

class commandSchema(Schema):
    """ /api/commands post

    Parameters:
     - command (str)
     - data (dict)
     - server (str)
    """
    command = fields.Str(required=True)
    server = fields.Str(required=True, error_messages={"required": "please specify a server to use."})
    data = fields.Dict(required=True, error_messages={"required": "please specify the data for the command."})

commandRenameRoomSchema = dictSchema({
    "command": str,
    "server": str,
    "data": {
        str: {
            "roomUID": str
        }
    }
})

commandShareRoomSchema = dictSchema({
    "command": str,
    "server": str,
    "data": {
        Use(str, error='specify roomUID'): {
            Use(is_email, error="please specify a valid mail address"): Optional(str, error='specify the name of the user')
        }
    }
}, error="please specify a room name and at least one valid mail address")

commandCreateRoomSchema = dictSchema({
    "command": str,
    "server": str,
    "data": {
        Use(str, error='specify room name'): {
            "email": Use(is_email, error="please specify a valid mail address"),
            Optional("roomUID"): Optional(str, error='specify the uid of the room'),
            Optional("accessCode"): Optional(str, error='specify the accessCode of the room')
        }
    }
}, error="please specify a room name and at least one valid mail address in the email field")

commandCreateUserSchema = dictSchema({
    "command": str,
    "server": str,
    "data": {
        Use(is_email, error="please specify a valid mail address"): {
            "fullName": str,
            Optional("pwd"): Optional(str, error='specify the password of the user'),
            Optional("role"): Optional(int, error='specify the role for the user'),
            Optional("provider"): Optional(str, error='specify the provider for the user')
        }
    }
}, error="please specify at least a valid mail address and the fullName.")
