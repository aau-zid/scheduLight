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
import sys, os, logging, urllib, json
import redis
from bigbluebutton_api_python import BigBlueButton
from bigbluebutton_api_python import util as bbbUtil
from bigbluebutton_api_python import exception as bbbexception
from datetime import datetime, timedelta
from socket import gethostbyname,gaierror 
import random
import string
import smtplib
import jinja2
from marshmallow import Schema, fields, INCLUDE, post_load, validates, ValidationError
from schema import Schema as dictSchema
from schema import And, Use, Optional, Regex, SchemaError
import dataSchema

class scheduLight:
    """ core functions for processing of commands and meetings  """
    
    # set startTime
    NOW = datetime.now()
    # prepare bbb
    bbb = None
    bbbUrl = None
    # keep status entris for n seconds
    keep_redis_cache ="31536000"
    # write to this logFile
    logFile = 'scheduLight.log'
    # define schemas
    meeting_schema = dataSchema.meetingSchema()
    server_schema = dataSchema.serverSchema()
    command_schema = dataSchema.commandSchema()
    command_rename_room_schema = dataSchema.commandRenameRoomSchema
    command_share_room_schema = dataSchema.commandShareRoomSchema
    command_create_room_schema = dataSchema.commandCreateRoomSchema
    command_create_user_schema = dataSchema.commandCreateUserSchema
    validate_schema = dataSchema.validate_schema

    def __init__(self, args={}):
        if 'keep_redis_cache' in args: 
            self.keep_redis_cache = args.keep_redis_cache
        if 'logFile' in args: 
            self.logFile = args.logFile

        ## create logger with 'scheduLight'
        self.logger = logging.getLogger('scheduLight')
        self.logger.setLevel(logging.DEBUG)
        ## create file handler which logs even debug messages
        fh = logging.handlers.RotatingFileHandler(self.logFile, maxBytes=1000000, backupCount=5)
        fh.setLevel(logging.DEBUG)
        ## create console handler with a higher log level
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ## create formatter and add it to the handlers
        formatter = logging.Formatter('%(asctime)s %(name)-12s %(levelname)-8s %(message)s', '%Y-%m-%d %H:%M:%S')
        fh.setFormatter(formatter)
        formatter2 = logging.Formatter('%(levelname)-8s %(message)s')
        ch.setFormatter(formatter2)
        ## add the handlers to the logger
        self.logger.addHandler(fh)
        self.logger.addHandler(ch)
        #

        # connect to redis db
        self.r = redis.StrictRedis( host="localhost", port="6380", db=1, ssl=False, charset="utf-8", decode_responses=True)
        try:
            self.r.info()
        except redis.exceptions.ConnectionError as ERR:
            self.logger.error("Redis not ready: {}".format(ERR))
            sys.exit()
        # prepare mail queue
        try:
            #self.r.xgroup_destroy('mailStream', 'mailNotifications')
            self.r.xgroup_create('mailStream', 'mailNotifications', '0-0', True)
        except Exception as ERR:
            self.logger.debug("Redis stream warning: {}".format(ERR))
        #prepare command queue
        try:
            #self.r.xgroup_destroy('commandStream', 'commandNotifications')
            self.r.xgroup_create('commandStream', 'commandNotifications', '0-0', True)
        except Exception as ERR:
            self.logger.debug("Redis stream warning: {}".format(ERR))

    def init_bbb(self, server):
        servers = {}
        res = self.r.get("server:{}".format(server))
        if res:
            servers[server] = json.loads(res)
            BBB_URL= servers[server]['BBB_URL']
            BBB_SECRET= servers[server]['BBB_SECRET']
            self.bbb = BigBlueButton(BBB_URL,BBB_SECRET)
            self.bbbUrl = bbbUtil.UrlBuilder(BBB_URL,BBB_SECRET)
            self.logger.debug("connected to bbb server: {}".format(server))
            return True
        else:
            self.logger.error("could not connect to bbb server: {}".format(server))
            return False
    def get_date(self, dateString):
        format_string = "%Y-%m-%d %H:%M"
        return datetime.strptime(dateString, format_string)
    
    def render_template(self, template, **kwargs):
        template_file = os.path.dirname(__file__)+'/templates/'+template
        if not os.path.exists(template_file):
            self.logger.error("Mail Template {} not found!".format(template_file))
            sys.exit()
        templateLoader = jinja2.FileSystemLoader(searchpath=os.path.dirname(__file__)+'/templates/')
        templateEnv = jinja2.Environment(loader=templateLoader)
        templ = templateEnv.get_template(template)
        return templ.render(**kwargs)
    
    def config_exists(self, my_dict, my_list):
        for my_item in my_list:
            if my_item not in my_dict:
                return False
        return True
    
    def random_secret(self, stringLength=11):
        lettersAndDigits = string.ascii_letters + string.digits
        return ''.join((random.choice(lettersAndDigits) for i in range(stringLength)))
    
    def get_status(self, base, path, displayType='returnCode', type='meeting'):
        search_base = "{}:{}:status".format(type, base)
        search_path = str.join("_", path)
        statusList = self.r.hget(search_base, search_path)
        if statusList == None:
            self.logger.debug("no status found for {} {}".format(base, search_path))
            return None
        statusList = json.loads(statusList)
        if not isinstance(statusList, list):
            self.logger.debug("corrupted status found for {}".format(base))
            return None
        self.r.touch(search_base)
        # return status
        if displayType == 'raw':
            return statusList
        (date, returnCode, message) = statusList[-1].split("|")
        self.logger.debug("status: {} {} {} ({})".format(returnCode, message, date, search_path))
        if displayType == 'date':
            return date
        elif displayType == 'returnCode':
            return returnCode
        else:
            return message

    def set_status(self, base, path, returnCode, message, type='meeting'):
        search_base = "{}:{}:status".format(type, base)
        search_path = str.join("_", path)
        oldStatus = self.get_status(base, path, 'raw', type)
        if oldStatus != None and oldStatus[-1].split('|')[1] == returnCode:
            self.logger.debug("status already set to {} {}".format(returnCode, message))
            return None
        else:
            if not isinstance(oldStatus, list):
                oldStatus = []
            oldStatus.append("{}|{}|{}".format(self.NOW, returnCode, message))
            self.r.hset(search_base, search_path, json.dumps(oldStatus))
            self.r.expire(search_base, self.keep_redis_cache)
            self.logger.debug("set status: {} {} ({})".format(returnCode, message, search_path))    
            return True

    def meeting_info(self, bbb_id):
        try:
            minfo = self.bbb.get_meeting_info(bbb_id)
        except bbbexception.BBBException as ERR:
            return 0
        return minfo
    
    def end_meeting(self, bbb_id):
        try:
            minfo = self.bbb.get_meeting_info(bbb_id)
        except bbbexception.BBBException as ERR:
            return 0
    
        moderator_pw = minfo.get_meetinginfo().get_moderatorpw()
        try:
            meetingsXML = self.bbb.end_meeting(bbb_id, moderator_pw)
        except bbbexception.BBBException as ERR:
            return 0
    
        if meetingsXML.get_field('returncode') == 'SUCCESS':
            if meetingsXML.get_field('messageKey') == 'sentEndMeetingRequest':
                self.logger.debug("meeting {}: {}".format(meetingName, meetingsXML.get_field('message')))
                return 1
        return 0
    
    def start_meeting(self, bbb_id, meetingTitle=None, moderatorPassword=None, attendeePassword=None, muteOnStart=None, welcome=None, bannerText=None, maxParticipants=None, logoutURL=None, record=None, duration=None, autoStartRecording=None, allowStartStopRecording=None):
        create_params = {}
        if moderatorPassword:
            create_params['moderatorPW'] = moderatorPassword
        if attendeePassword:
            create_params['attendeePW'] = attendeePassword
        if muteOnStart:
            create_params['muteOnStart'] = muteOnStart
        if welcome:
            create_params['welcome'] = welcome
        if bannerText:
            create_params['bannerText'] = bannerText
        if maxParticipants:
            create_params['maxParticipants'] = maxParticipants
        if logoutURL:
            create_params['logoutURL'] = "https://{}".format(logoutURL)
        if record:
            create_params['record'] = record
        if duration:
            create_params['duration'] = duration
        if autoStartRecording:
            create_params['autoStartRecording'] = autoStartRecording
        if allowStartStopRecording:
            create_params['allowStartStopRecording'] = allowStartStopRecording
        if meetingTitle:
            create_params['name'] = meetingTitle
        try:
            meetingsXML = self.bbb.create_meeting(bbb_id, params=create_params)
        except bbbexception.BBBException as ERR:
            self.logger.error(ERR)
            return 0
        if meetingsXML.get_field('returncode') == 'SUCCESS':
            if meetingsXML.get_field('messageKey') == 'duplicateWarning':
                self.logger.debug("meeting already running: {}".format(meetingsXML.get_field('message')))
            if meetingsXML.get_field('hasUserJoined') == 'false':
                self.logger.debug("no users have joined yet, keeping open")
                # keep open
                return 2
            # users have joined - stop processing
            self.logger.debug("users have joined stopping to process")
            return 1
        # failed to start meeting
        self.logger.debug("failed to start meeting")
        return 0
    
    def get_join_url(self, id, name, role='attendee', pw=None):
        pwd = None
        if pw:
            pwd = pw
        elif self.meeting_info(id):
            minfo = self.meeting_info(id)
            if role == 'moderator':
                pwd = minfo.get_meetinginfo().get_moderatorpw()
            elif role == 'attendee':
                pwd = minfo.get_meetinginfo().get_attendeepw()
        if pwd:
            return self.bbb.get_join_meeting_url(name, id, pwd)
    
    def get_meetings(self, server):
        self.logger.debug("fetching meetings from {}".format(server))
        try:
            meetingsXML = self.bbb.get_meetings()
            if meetingsXML.get_field('returncode') == 'SUCCESS':
                if  meetingsXML.get_field('meetings') == '':
                    self.logger.debug("no meetings running on {}".format(server))
                    return []
                else:
                    rawMeetings = meetingsXML.get_field('meetings')['meeting']
                    if isinstance(rawMeetings, list):
                        self.logger.debug("meetings found on {}".format(server))
                        return json.loads(json.dumps(rawMeetings))
                    else:
                        self.logger.debug("meeting found on {}".format(server))
                        return [json.loads(json.dumps(rawMeetings))]
            else:
                self.logger.error("api request failed")
                return []
        except urllib.error.URLError as ERR:
            self.logger.error(ERR)
            return []
    
    def find_meeting(self, server, title, user='system_administrator'):
        meetings = self.get_meetings(server)
        for meeting in meetings:
            if title in meeting['meetingName']:
                meeting['joinAttendeeUrl'] = self.get_join_url(meeting['meetingID'], user, 'attendee')
                meeting['joinModeratorUrl'] = self.get_join_url(meeting['meetingID'], user, 'moderator')
    
                joinParams = {}
                joinParams['meetingID'] = meeting['meetingID']
                joinParams['fullName'] = user
                joinParams['password'] = meeting['attendeePW']    
                joinParams['userdata-bbb_auto_join_audio'] = "true"
                joinParams['userdata-bbb_enable_video'] = 'false'
                joinParams['userdata-bbb_listen_only_mode'] = "false"
                joinParams['userdata-bbb_skip_check_audio'] = 'true'
                meeting['joinDirectWithMicUrl'] = self.bbbUrl.buildUrl("join", params=joinParams)
                return meeting
    
    def show_meetings(self, server, user='system_administrator'):
        meetings = self.get_meetings(server)
        for meeting in meetings:
            print(meeting['meetingName'])
            print("ID: {}".format(meeting['meetingID']))
            print("ATTENDEE_PASSWORD: {}".format(meeting['attendeePW']))
            joinAttendeeUrl = self.get_join_url(meeting['meetingID'], user, 'attendee')
            print("JOIN_ATTENDEE_URL: {}".format(joinAttendeeUrl))
            print("MODERATOR_PASSWORD: {}".format(meeting['moderatorPW']))
            joinModeratorUrl = self.get_join_url(meeting['meetingID'], user, 'moderator')
            print("JOIN_MODERATOR_URL: {}".format(joinModeratorUrl))
            print("")
    