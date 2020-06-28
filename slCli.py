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
import sys
import argparse
import yaml, json
import logging, logging.handlers
import time
from scheduLight import scheduLight
from bigbluebutton_api_python import BigBlueButton
from bigbluebutton_api_python import util as bbbUtil
from bigbluebutton_api_python import exception as bbbexception
from greenLight import greenLight

def parseArgs():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dbName", help="Database name", default="greenlight_production")
    parser.add_argument("--dbUser", help="Database user", default="postgres")
    parser.add_argument("--dbPassword", help="Database password", default="")
    parser.add_argument("--dbHost", help="Database host", default="127.0.0.1")
    parser.add_argument("--dbPort", help="Database port", default="5432")
    parser.add_argument("-f","--find_meeting", help="find running Meeting by title")
    parser.add_argument("-d","--debug_emails", help="print mails insttead of sending them", action="store_true")
    parser.add_argument("-n","--no_emails", help="prevent sending of emails", action="store_true")
    parser.add_argument("-m","--showMeetings", help="fetch  running meetings from configured servers and print infos", action="store_true")
    parser.add_argument("-g","--logFile", help="path to logFile in yaml format", default="./scheduLight.log")
    parser.add_argument("-l","--room_links", help="show links of rooms specified by its name (or optional by -b --room_by ...)")
    parser.add_argument("-e","--email", help="emailaddress to use for sending mails (for commandline)")
    parser.add_argument("-b","--room_by", help="show links of a room by this column", default="name")
    parser.add_argument("-r","--reminder_minutes", help="set the reminder to n minutes before the start of the meeting (if startDate was provided)")
    parser.add_argument("-p","--pre_open", help="pre open the meeting n minutes before the startDate", default=90)
    parser.add_argument("-P","--pre_start", help="pre start the meeting n minutes before the startDate", default=0)
    parser.add_argument("-a","--end_after", help="end the meeting n minutes aftter the startDate", default=0)
    parser.add_argument("-c","--configFile", help="path to config file in yaml format", default="./config.yml")
    parser.add_argument("-s","--server", help="server to use (has to be configured)", default="bbb")
    parser.add_argument("-S","--store_result", help="store result to configFile", action="store_true")
    return parser.parse_args()

def write_yaml(dataFile,config):
    with open(dataFile, 'w') as outfile:
        yaml.dump(config, outfile, default_flow_style=False, allow_unicode=True)

def read_yaml(dataFile, ignore_missing_file = False):
    try:
        with open(dataFile, 'r') as stream:
            try:
                return yaml.load(stream, Loader=yaml.SafeLoader)
            except yaml.YAMLError as ERR:
                logger.error(ERR)
                sys.exit()
    except FileNotFoundError as ERR:
        if ignore_missing_file  != True:
            sys.exit()
#############
### start ###
#parse the commandline arguments
args = parseArgs()

## create logger with 'cli'
logger = logging.getLogger('cli')
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
logger.debug("initializing scheduLight...")
sl = scheduLight(args)
#
# run application 
# set startTime
NOW = datetime.now()
logger.debug("Date: {}".format(NOW))
# read configFile
logger.debug("loading config from file...")
meetingsConfig = read_yaml(args.configFile)
if 'meetings' not in meetingsConfig:
    meetingsConfig['meetings'] = {}
# show running meetings
if args.showMeetings:
    if sl.init_bbb(args.server):
        sl.show_meetings(args.server)

# find running meeting by title and optionally append to configFile
elif args.find_meeting:
    logger.debug("searching running meeting with title {} on server {}...".format(args.find_meeting, args.server))
    if sl.init_bbb(args.server):
        meeting = sl.find_meeting(args.server, args.find_meeting)
        if meeting:
            logger.debug("found running meeting with title {}...".format(args.find_meeting))
            print(meeting)
            if args.store_result:
                meetingsConfig['meetings'][meeting['meetingID']] = meeting
                write_yaml(args.configFile, meetingsConfig)

# show meeting links and optional send via email...
elif args.room_links:
    logger.debug("searching rooms with {} {}...".format(args.room_by, args.room_links))
    rooms = {}
    if args.room_links == 'meetings':
        for meeting in sl.r.smembers('meetings'):
            logger.debug("processing meeting {}...".format(meeting))
            mDict = json.loads(sl.r.get('meeting:{}'.format(meeting)))
            errors = sl.meeting_schema.validate(mDict)
            if errors:
                logger.error("please provide all required fields for the meeting: {}".format(errors))
                continue

            servers = {}
            server = mDict['server']
            res = sl.r.get("server:{}".format(server))
            if res:
                servers[server] = json.loads(res)
                logger.debug("load server: {}".format(server))
            else:
                logger.error("could not load server: {}".format(server))
                sys.exit()
            logger.debug("loading config for {}...".format(server))
            errors = sl.server_schema.validate(servers[server])
            if errors:
                logger.error("please provide all required fields for the server: {}".format(errors))
                continue

            if not sl.init_bbb(mDict[server]):
                logger.error("Could not connect to bbb server: {}".format(mDict[server]))
                continue

            if 'useHomeRoom' in mDict and mDict['useHomeRoom'] == True:
                room_id = gl.get_table_field('email', 'users', mDict['owner']['email'], 'room_id')
            elif mDict['meetingUID']:
                #check if meetingUID exists and fetch room_id
                room_id = gl.get_table_field('rooms', 'uid', mDict['meetingUID'], 'id')
            else:
                logger.error("could not fetch room for this meeting: {}".format(mDict['meetingName']))
                continue
            rooms[room_id] = gl.table_row_as_dict('rooms', 'id', room_id, gl.roomsTableList)
    else:
        server = args.server
        servers = {}
        res = sl.r.get("server:{}".format(server))
        if res:
            servers[server] = json.loads(res)
            logger.debug("load server: {}".format(server))
        else:
            logger.error("could not load server: {}".format(server))
            sys.exit()
        logger.debug("loading config for {}...".format(server))
        errors = sl.server_schema.validate(servers[server])
        if errors:
            logger.error("please provide all required fields for the server: {}".format(errors))
            sys.exit()
        if not sl.init_bbb(server):
            logger.error("Could not connect to bbb server: {}".format(server))
            sys.exit()
        rooms = gl.table_rows_as_dict('rooms', args.room_by, args.room_links, gl.roomsTableList)
        if not rooms:
            logger.error("no rooms found")
            sys.exit()
        roomLinks = ""
        for room in rooms:
            room_data = rooms[room]
            user_data = gl.table_row_as_dict('users', 'id', room_data['user_id'], gl.usersTableList)
            if 'id' not in user_data:
                logger.error("no userdata found for {}...".format(room_data['user_id']))
                continue
            #prepare moderator and meeting room link
            if args.email:
                moderatorName = args.email.partition('@')[0]
            elif args.email == user_data['email']:
                moderatorName = user_data['name']
            else:
                moderatorName = "Moderator"
            moderatorLink = sl.get_join_url(room_data['bbb_id'], moderatorName, 'moderator', room_data['moderator_pw'])
            ownerModeratorLink = sl.get_join_url(room_data['bbb_id'], user_data['name'], 'moderator', room_data['moderator_pw'])
            meetingLink = "{}/{}".format(servers[server]['link_base'], room_data['uid'])
            meetingKey = user_data['email'].replace('@', '_').replace('.', '_')
            meeting = None
            startDate = ""
            if meetingKey in meetingsConfig['meetings']:
                meeting = meetingsConfig['meetings'][meetingKey]
            if meeting != None and 'startDate' in meeting:
                startDate = meeting['startDate']
            # create room links 
            createLinks = """
----
{}: {}
Email: {}
Startdate: {}
Meeting Link: {}
Moderator Link ({}): {}
Moderator Link ({}): {}
            """.format(user_data['name'], room_data['name'], user_data['email'], startDate, meetingLink, moderatorName, moderatorLink, user_data['name'], ownerModeratorLink)
            roomLinks = roomLinks + createLinks

        # print the room links
        print(roomLinks)

        if args.email:
            logger.debug("sending meeting links via email...")
            # prepare and send mail
            subject = "Subject: room links for {}: {}\n".format(args.room_by, args.room_links)
            roomLinks = subject + roomLinks

            fullName = args.email.partition('@')[0]
            # mail server configs
            mail_properties = {}
            mail_properties['mailServer'] = servers[server]['mailServer']
            mail_properties['mailUser'] = servers[server]['mailUser']
            mail_properties['mailPassword'] = servers[server]['mailPassword']
            # sender and receiver
            mail_properties['mailFrom'] = user_data['email']
            if 'mailFrom' in servers[server]:
                mail_properties['mailFrom'] = servers[server]['mailFrom']
            # set mailFromName as required but override if provided on server or meeting basis
            mail_properties['mailFromName'] = user_data['name']
            if 'mailFromName' in servers[server]:
                mail_properties['mailFromName'] = servers[server]['mailFromName']
            # set mailTo as required but override if provided on server or meeting basis
            mail_properties['mailTo'] = args.email
            # set mailToName as required but override if provided on server or meeting basis
            mail_properties['mailToName'] = fullName
            mail_properties['mailText'] = roomLinks
            mail_properties['contentType'] = "plain"
            try:
                res = sl.r.xadd('mailStream', { meeting: json.dumps(mail_properties) })
                logger.debug("queued mail successfully")
            except Exception as ERR:
                logger.error("failed to send mail to queue.")

# shut down application
logger.info("shutting down...")
gl.close()
sl.r.bgsave()
sl.r.connection_pool.disconnect()
