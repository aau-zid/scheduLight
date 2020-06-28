#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# scheduLight - automation tool for BigBlueButton and Greenlight
# copyright Martin Thomas Schrott 2020
#
# This file is part of scheduLight
# scheduLight is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
# You should have received a copy of the GNU General Public License along with Foobar.  If not, see <https://www.gnu.org/licenses/>.
#
from datetime import datetime, timedelta
import argparse
import json
import logging, logging.handlers
import time
import signal
from scheduLight import scheduLight
from bigbluebutton_api_python import BigBlueButton
from bigbluebutton_api_python import util as bbbUtil
from bigbluebutton_api_python import exception as bbbexception
from greenLight import greenLight

def sigint_handler(sig, frame):
    logger.debug("received {}...".format(sig))
    global stop
    stop = True

def parseArgs():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbName", help="Database name", default="greenlight_production")
    parser.add_argument("--dbUser", help="Database user", default="postgres")
    parser.add_argument("--dbPassword", help="Database password", default="")
    parser.add_argument("--dbHost", help="Database host", default="127.0.0.1")
    parser.add_argument("--dbPort", help="Database port", default="5432")
    parser.add_argument("-f","--findcommand", help="find running command by title")
    parser.add_argument("-d","--debug_emails", help="print mails insttead of sending them", action="store_true")
    parser.add_argument("-n","--no_emails", help="prevent sending of emails", action="store_true")
    parser.add_argument("-m","--showcommands", help="fetch  running commands from configured servers and print infos", action="store_true")
    parser.add_argument("-g","--logFile", help="path to logFile in yaml format", default="./scheduLight.log")
    parser.add_argument("-l","--room_links", help="show links of rooms of an user specified here by email (or optional by -b --room_by ...)")
    parser.add_argument("-e","--email", help="emailaddress to use for sending mails (for commandline)")
    parser.add_argument("-b","--room_by", help="show links to room of an user by this column", default="email")
    parser.add_argument("-r","--reminder_minutes", help="set the reminder to n minutes before the start of the command (if startDate was provided)")
    parser.add_argument("-p","--pre_open", help="pre open the command n minutes before the startDate", default=90)
    parser.add_argument("-P","--pre_start", help="pre start the command n minutes before the startDate", default=0)
    parser.add_argument("-a","--end_after", help="end the command n minutes aftter the startDate", default=0)

    return parser.parse_args()

def process_command(cDict):
    errors = sl.command_schema.validate(cDict)
    if errors:
        logger.error("please provide all required fields for the command: {}".format(errors))
        return False
    command = cDict['command']
    logger.debug("processing command '{}'...".format(command))

    servers = {}
    server = cDict['server']
    res = sl.r.get("server:{}".format(server))
    if res:
        servers[server] = json.loads(res)
        logger.debug("load server: {}".format(server))
    else:
        logger.error("could not load server: {}".format(server))
        return False
    logger.debug("loading config for {}...".format(server))
    errors = sl.server_schema.validate(servers[server])
    if errors:
        logger.error("please provide all required fields for the server: {}".format(errors))
        return False

    cElementList = set(cDict['data'])
    success = True
    for cElement in cElementList:
        cData = cDict['data'][cElement]
        if command == 'rename_room':
        # rename room
            errors = sl.validate_schema(sl.command_rename_room_schema, cDict)
            if errors:
                logger.error("please specify all required fields. {}".format(errors))
                success = False
            logger.debug("renaming room {} to {}...".format(cElement, cData['roomUID']))

            if gl.rename_room(cElement, cData['roomUID']):
                logger.info("renamed room {} to {}".format(cElement, cData['roomUID']))
            else:
                logger.error("could not rename room {} to {}".format(cElement, cData['roomUID']))
                success = False

        elif command == 'share_room':
        # share room
            errors = sl.validate_schema(sl.command_share_room_schema, cDict)
            if errors:
                logger.error("please specify all required fields. {}".format(errors))
                success = False
            for email in cData:
                logger.debug("sharing room {} with {}...".format(cElement, email))
                if gl.share_room(cElement, email, 'uid'):
                    logger.info("shared room {} with {}".format(cElement, email))
                    # send mail
                    mail_properties = {}
                    mail_properties['mailServer'] = servers[server]['mailServer']
                    mail_properties['mailUser'] = servers[server]['mailUser']
                    mail_properties['mailPassword'] = servers[server]['mailPassword']
                    mail_properties['mailFrom'] = servers[server]['mailFrom']
                    mail_properties['mailFromName'] = servers[server]['mailFromName']
                    mail_properties['mailTo'] = email
                    if cData[email]:
                        mail_properties['mailToName'] = cData[email]
                    else:
                        mail_properties['mailToName'] = email.partition('@')[0]
                    meetingLink = "{}/{}".format(servers[server]['link_base'], cElement)
                    mail_properties['mailText'] = sl.render_template("roomSharedTemplate.j2", vars=locals())
                    try:
                        res = sl.r.xadd('mailStream', { command: json.dumps(mail_properties) })
                        logger.info("queued mail successfully. {}".format(res))
                    except Exception as ERR:
                        logger.error("failed to send mail to queue. {} {}".format(res, ERR))
                        success = False
                else:
                    logger.error("room {} could not be shared with {}...".format(cElement, email))
                    success = False

        elif command == 'unshare_room':
        # unshare room
            errors = sl.validate_schema(sl.command_share_room_schema, cDict)
            if errors:
                logger.error("please specify all required fields. {}".format(errors))
                success = False
            for email in cData:
                logger.debug("sharing room {} with {}...".format(cElement, email))
                if gl.unshare_room(cElement, email, 'uid'):
                    logger.info("unshared room {} with {}".format(cElement, email))
                    # send mail
                    mail_properties = {}
                    mail_properties['mailServer'] = servers[server]['mailServer']
                    mail_properties['mailUser'] = servers[server]['mailUser']
                    mail_properties['mailPassword'] = servers[server]['mailPassword']
                    mail_properties['mailFrom'] = servers[server]['mailFrom']
                    mail_properties['mailFromName'] = servers[server]['mailFromName']
                    mail_properties['mailTo'] = email
                    if cData[email]:
                        mail_properties['mailToName'] = cData[email]
                    else:
                        mail_properties['mailToName'] = email.partition('@')[0]
                    meetingLink = "{}/{}".format(servers[server]['link_base'], cElement)
                    mail_properties['mailText'] = sl.render_template("roomUnsharedTemplate.j2", vars=locals())
                    try:
                        res = sl.r.xadd('mailStream', { command: json.dumps(mail_properties) })
                        logger.info("queued mail successfully. {}".format(res))
                    except Exception as ERR:
                        logger.error("failed to send mail to queue. {} {}".format(res, ERR))
                        success = False
                else:
                    logger.error("room {} could not be unshared with {}...".format(cElement, email))
                    success = False

        elif command == 'delete_room':
        # delete room
            logger.debug("deleting room {}...".format(cElement))
            if gl.delete_room(cElement):
                logger.info("deleted room {}".format(cElement))
            else:
                logger.error("could not delete room {}".format(cElement))
                success = False

        elif command == 'create_room':
        # create room
            errors = sl.validate_schema(sl.command_create_room_schema, cDict)
            if errors:
                logger.error("please specify all required fields. {}".format(errors))
                success = False
            logger.debug("creating room {} for {}...".format(cElement, cData['email']))
            alias = None
            if 'roomUID' in cData:
                alias = cData['roomUID']
            accessCode = None
            if 'accessCode' in cData:
                accessCode = cData['accessCode']
            if gl.create_room(cData['email'], cElement, alias, None, None, None, None, accessCode):
                logger.info("created room {} for {}".format(cElement, cData['email']))
            else:
                logger.error("could not create room {} for {}".format(cElement, cData['email']))
                success = False

        elif command == 'delete_user':
        # delete user
            logger.debug("deleting user {}...".format(cElement))
            if gl.delete_user(cElement):
                logger.info("{} {}".format(command, cElement))
            else:
                logger.error("could not delete user {}".format(cElement))
                success = False

        elif command == 'create_user':
        # create user
            errors = sl.validate_schema(sl.command_create_user_schema, cDict)
            if errors:
                logger.error("please specify all required fields. {}".format(errors))
                success = False
            logger.debug("creating user {} {}...".format(cElement, cData['fullName']))
            pwd = None
            if 'pwd' in cData:
                pwd = cData['pwd']
            role = None
            if 'role' in cData:
                role = cData['role']
            provider = None
            if 'provider' in cData:
                provider = cData['provider']
            if gl.create_user(cElement, cData['fullName'], pwd, role, provider):
                logger.info("created user {} {}".format(cElement, cData['fullName']))
            else:
                logger.error("could not create user {}".format(cElement))
                success = False
    return success
#############
### start ###
#parse the commandline arguments
args = parseArgs()
stop = False
# signal processing
signal.signal(signal.SIGTERM, sigint_handler)
signal.signal(signal.SIGINT, sigint_handler)


## create logger with 'commandProcessor'
logger = logging.getLogger('commandProcessor')
logger.setLevel(logging.INFO)
## create file handler which logs even debug messages
fh = logging.handlers.RotatingFileHandler(args.logFile, maxBytes=1000000, backupCount=5)
fh.setLevel(logging.INFO)
## create console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
## create formatter and add it to the handlers
formatter = logging.Formatter('%(asctime)s %(name)-12s %(levelname)-8s %(message)s', '%Y-%m-%d %H:%M:%S')
fh.setFormatter(formatter)
formatter2 = logging.Formatter('%(levelname)-8s %(message)s')
ch.setFormatter(formatter2)
## add the handlers to the logger
logger.addHandler(fh)
logger.addHandler(ch)
#
logger.debug("starting...")
# initialize greenlight
logger.debug("initializing greenlight...")
gl = greenLight(args.dbName, args.dbUser, args.dbPassword, args.dbHost, args.dbPort, args.logFile)
# init sheduLight instance
sl = scheduLight(args)
#
# run application 
while True:
    # set startTime
    NOW = datetime.now()
    logger.debug("Date: {}".format(NOW))
    # process commands
    try:
        sl.r.xreadgroup('commandNotifications', 'consumer1', { 'commandStream': '0' }, None, None, True)
    except Exception as ERR:
        logger.debug(ERR)
        break
    logger.debug("process old messages")
    for stream in sl.r.xreadgroup('commandNotifications', 'consumer1', { 'commandStream': '0' }, None, None, False):
        logger.debug("Stream: {}".format(stream[0]))
        for msg in stream[1]:
            (id, item) = msg
            logger.debug("id: {}".format(id))
            logger.debug("item: {}".format(item))
            for key in item:
                cDict = json.loads(item[key])
            if process_command(cDict):
                logger.info("command {} {} processed successfully".format(id, cDict['command']))
                logger.debug("ack msg: {}".format(sl.r.xack('commandStream', 'commandNotifications', id)))
            else:
                logger.error("Errors during processing of command. More information can be found in the logfile")
                logger.debug("ack msg: {}".format(sl.r.xack('commandStream', 'commandNotifications', id)))

    logger.debug("process new commands")
    for stream in sl.r.xreadgroup('commandNotifications', 'consumer1', { 'commandStream': '>' }, None, None, False):
        logger.debug("Stream: {}".format(stream[0]))
        for msg in stream[1]:
            (id, item) = msg
            logger.debug("id: {}".format(id))
            logger.debug("item: {}".format(item))
            for key in item:
                cDict = json.loads(item[key])
            if process_command(cDict):
                logger.info("command {} {} processed successfully".format(id, cDict['command']))
                logger.debug("ack msg: {}".format(sl.r.xack('commandStream', 'commandNotifications', id)))
            else:
                logger.error("Errors during processing of command. More information can be found in the logfile")
                logger.debug("ack msg: {}".format(sl.r.xack('commandStream', 'commandNotifications', id)))

    # shut down
    time.sleep(1)
    if stop:
        logger.info("shutting down...")
        gl.close()
        sl.r.bgsave()
        sl.r.connection_pool.disconnect()
        break
