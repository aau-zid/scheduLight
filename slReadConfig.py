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
import logging.handlers
import argparse, sys, os, logging, yaml, json
from datetime import datetime, timedelta
from scheduLight import scheduLight

def parseArgs():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c","--configFile", help="path to config file in yaml format", default="./config.yml")
    parser.add_argument("-k","--keep_redis_cache", help="keep the status and config in redis cache for n seconds", default="31536000")
    parser.add_argument("-i","--importCSV", help="path to meetings csv file to import")
    parser.add_argument("-d","--delete_meetings", help="delete meetings from redis if they where remove from the config file", action="store_true")
    parser.add_argument("-g","--logFile", help="path to logFile in yaml format", default="./scheduLight.log")
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

## create logger with 'readConfig'
logger = logging.getLogger('readConfig')
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
# init sheduLight instance
sl = scheduLight(args)
# set startTime
NOW = datetime.now()
logger.debug("Date: {}".format(NOW))

# loading config
logger.debug("loading config from {}...".format(args.configFile))
meetingsConfig = read_yaml(args.configFile)

#import meetings csv to configFile
if args.importCSV:
    logger.debug("import meetings csv from {} to config file...".format(args.importCSV))
    if 'meetings' not in meetingsConfig:
        meetingsConfig['meetings'] = {}
    mDict = meetingsConfig['meetings']

    with open(args.importCSV, 'r') as csv:
        for line in csv:
            (givenname, sn, email, password, startdate, room_url, live_url, title, server) = line.strip().split(';')
            givenname = givenname.strip()
            sn = sn.strip()
            name = "{} {}".format(givenname, sn)
            orig_email = email.strip()
            email = email.lower().strip()
            password = password.strip()
            startdate = startdate.strip()
            if startdate  == '0000-00-00':
                startdate = None
            meetingTitle = title
            meetingKey = email.replace('@', '_').replace('.', '_')
            server = server.strip()

            # meeting infos
            mDict[meetingKey] = {}
            mDict[meetingKey]['id'] = meetingKey
            mDict[meetingKey]['server'] = server
            mDict[meetingKey]['meetingName'] = "{}".format(name)
            mDict[meetingKey]['meetingTitle'] = meetingTitle
            if startdate:
                mDict[meetingKey]['startDate'] = startdate
            # owner info
            mDict[meetingKey]['owner'] = {}
            mDict[meetingKey]['useHomeRoom'] = True
            mDict[meetingKey]['owner']['email'] = email
            mDict[meetingKey]['owner']['password'] = password
            mDict[meetingKey]['owner']['socialUid'] = "CN={},OU=USERS,OU=EXTERNAL,DC=ldap,DC=domain,DC=tld".format(orig_email)
            mDict[meetingKey]['owner']['fullName'] = name
            # templates
            mDict[meetingKey]['meetingOwnerInfoTemplate'] = "imported-meetingOwnerInfoTemplate.j2"
            mDict[meetingKey]['meetingModeratorInfoTemplate'] = "imported-meetingModeratorInfoTemplate.j2"
            mDict[meetingKey]['meetingShareInfoTemplate'] = "imported-meetingShareInfoTemplate.j2"
            mDict[meetingKey]['meetingInvitationInfoTemplate'] = "imported-meetingInvitationInfoTemplate.j2"
            mDict[meetingKey]['meetingOwnerStartedTemplate'] = "imported-meetingOwnerStartedTemplate.j2"
            mDict[meetingKey]['meetingOwnerReminderTemplate'] = "imported-meetingOwnerReminderTemplate.j2"
            #settings
            mDict[meetingKey]['muteOnStart'] = "true"
#                        mDict[meetingKey]['welcome'] = None
#                        mDict[meetingKey]['bannerText'] = None
            mDict[meetingKey]['maxParticipants'] = 150
            mDict[meetingKey]['logoutURL'] = "importet.logout.url"
#                        mDict[meetingKey]['record'] = None
#                        mDict[meetingKey]['duration'] = None
#                        mDict[meetingKey]['autoStartRecording'] = False
#                        mDict[meetingKey]['allowStartStopRecording'] = None
            #mDict[meetingKey]['accessCode'] = ""
                        # prepare         liveStreaming parameters
            mDict[meetingKey]['liveStreaming'] = {}
            mDict[meetingKey]['liveStreaming']['playIntro'] = "/video/5min.mp4"
            mDict[meetingKey]['liveStreaming']['streamerHost'] = live_url
            mDict[meetingKey]['liveStreaming']['targetUrl'] = "rtmp://{}/stream/bbb".format(live_url)
    write_yaml(args.configFile, meetingsConfig)

# read config from file
else:
    if 'servers'  in meetingsConfig:
        serversList = set(meetingsConfig['servers'])
        # update servers list in redis
        if sl.r.exists('servers'):
            logger.debug("store last servers to compare: {}".format(sl.r.rename('servers', 'oldservers')))
        # process servers in config
        for server in serversList:
            logger.debug("processing {}...".format(server))
            errors = sl.server_schema.validate(meetingsConfig['servers'][server])
            if errors:
                logger.error("please provide all required fields for the server: {}".format(errors))
                continue

            try:
                sl.r.sadd('servers', server)
                sl.r.set('server:{}'.format(server), json.dumps(meetingsConfig['servers'][server]))
                sl.r.expire('server:{}'.format(server), args.keep_redis_cache)
                logger.info("added server {}".format(server))
            except Exception as ERR:
                logger.error("failed to add server {} to queue. {}".format(m, ERR))
        if args.delete_meetings:
            # delete servers that where removed from the configFile
            logger.debug("store removed servers for deletion: {}".format(sl.r.sdiffstore('delservers', 'oldservers', 'servers')))
            for server in sl.r.smembers('delservers'):
                logger.info("Remove server: {}".format(server))
                sl.r.delete("server:{}".format(server))
                sl.r.delete("server:{}:status".format(server))
                sl.r.srem('servers', server)
        logger.debug("clear cache of removed servers: {}".format(sl.r.delete('oldservers')))

    if 'meetings' in meetingsConfig:
        # update meetings list in redis
        if sl.r.exists('meetings'):
            logger.debug("store last meetings to compare: {}".format(sl.r.rename('meetings', 'oldMeetings')))
        meetingsList = set(meetingsConfig['meetings'])
        for m in meetingsList:
            logger.debug("processing {}...".format(m))
            errors = sl.meeting_schema.validate(meetingsConfig['meetings'][m])
            if errors:
                logger.error("please provide all required fields for the meeting: {}".format(errors))
                continue
            try:
                sl.r.sadd('meetings', m)
                sl.r.set('meeting:{}'.format(m), json.dumps(meetingsConfig['meetings'][m]))
                sl.r.expire('meeting:{}'.format(m), args.keep_redis_cache)
                logger.info("added meeting {}".format(m))
            except Exception as ERR:
                logger.error("failed to add meeting {} to queue. {}".format(m, ERR))
        if args.delete_meetings:
            # delete meetings that where removed from the configFile
            logger.debug("store removed meetings for deletion: {}".format(sl.r.sdiffstore('delMeetings', 'oldMeetings', 'meetings')))
            for meeting in sl.r.smembers('delMeetings'):
                logger.info("Remove meeting: {}".format(meeting))
                sl.r.delete("meeting:{}".format(meeting))
                sl.r.delete("meeting:{}:status".format(meeting))
                sl.r.srem('meetings', meeting)
        logger.debug("clear cache of removed meetings: {}".format(sl.r.delete('oldMeetings')))

    if 'commands' in meetingsConfig:
        # add commands to redis queue 
        commandsList = set(meetingsConfig['commands'])
        for m in commandsList:
            logger.debug("processing {}...".format(m))
            errors = sl.command_schema.validate(meetingsConfig['commands'][m])
            if errors:
                logger.error("please provide all required fields for the command: {}".format(errors))
                continue
            # put command to queue
            try:
                res = sl.r.xadd('commandStream', { m: json.dumps(meetingsConfig['commands'][m]) })
                logger.info("queued command {}".format(m))
            except Exception as ERR:
                logger.error("failed to queue command {} to queue. {}".format(m, ERR))

# shut down
sl.r.bgsave()
sl.r.connection_pool.disconnect()
