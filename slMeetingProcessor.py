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
import subprocess
import json
import logging, logging.handlers
import time
import signal
from scheduLight import scheduLight
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
    parser.add_argument("-d","--debug_emails", help="print mails insttead of sending them", action="store_true")
    parser.add_argument("-n","--no_emails", help="prevent sending of emails", action="store_true")
    parser.add_argument("-g","--logFile", help="path to logFile in yaml format", default="./scheduLight.log")
    parser.add_argument("-r","--reminder_minutes", help="set the reminder to n minutes before the start of the meeting (if startDate was provided)")
    parser.add_argument("-p","--pre_open", help="pre open the meeting n minutes before the startDate", default=90)
    parser.add_argument("-P","--pre_start", help="pre start the meeting n minutes before the startDate", default=0)
    parser.add_argument("-a","--end_after", help="end the meeting n minutes aftter the startDate", default=0)
    return parser.parse_args()

#############
### start ###
#parse the commandline arguments
args = parseArgs()
stop = False
# signal processing
signal.signal(signal.SIGTERM, sigint_handler)
signal.signal(signal.SIGINT, sigint_handler)


## create logger with 'meetingProcessor'
logger = logging.getLogger('meetingProcessor')
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
    # process all meetings on the server
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
            continue
        logger.debug("loading config for {}...".format(server))
        errors = sl.server_schema.validate(servers[server])
        if errors:
            logger.error("please provide all required fields for the server: {}".format(errors))
            continue

        # set send_emails for this server:
        send_emails = False
        if 'send_emails' in servers[server]:
            send_emails = servers[server]['send_emails']
        server_send_emails = send_emails
        # set send_emails status of meeting
        send_emails = server_send_emails
        if 'send_emails' in mDict:
            send_emails = mDict['send_emails']
        meeting_send_emails  = send_emails 

        # init bbb
        if not sl.init_bbb(server):
            logger.error("Could not connect to bbb server: {}".format(server))
            continue

        # get status of the meetings
        if not sl.get_status(meeting, ['status']):
            sl.set_status(meeting, ['status'], '200', 'new')
        # process meetings
        # if not disabled (status 900)
        if sl.get_status(meeting, ['status']) != '900':
            # check if owner was provided with email otherwise fail
            if 'owner' in mDict:
                if 'email' in mDict['owner']:
                    ownerEmail = mDict['owner']['email'].lower()
                    if 'fullName' in mDict['owner']:
                        ownerFullName = mDict['owner']['fullName']
                    else:
                        ownerFullName = mDict['owner']['email'].partition('@')[0]
                    if 'socialUid' in mDict['owner']:
                        socialUid = mDict['owner']['socialUid']
                    else:
                        socialUid = None
                    if 'password' in mDict['owner']:
                        ownerPassword = mDict['owner']['password']
                    else:
                        ownerPassword = None
                    if 'uid' in mDict['owner']:
                        ownerUid = mDict['owner']['uid']
                    else:
                        ownerUid = None

                    # process owner 
                    user_id = gl.get_id_by_email(ownerEmail)
                    if not user_id:
                        logger.error("user {} does not exist. creating new user...".format(ownerEmail))
                        user_id = gl.create_user(ownerEmail, ownerFullName, ownerUid, socialUid, ownerPassword)
                        if user_id == 0:
                            logger.error("user {} could not be created".format(ownerEmail))
                            sl.set_status(meeting, ['status'], '404', 'owner not found and creation failed')
                            continue

                    #check if meetingID was provided 
                    meetingID = None
                    if 'meetingID' in mDict:
                        meetingID = mDict['meetingID']
                        logger.debug("set meetingID to {}...".format(meetingID))
                    # check if meetingName was provided
                    meetingName = None
                    if 'meetingName' in mDict:
                        meetingName = mDict['meetingName']
                    else:
                        meetingName = ownerFullName 
                    logger.debug("set meetingName to {}...".format(meetingName))
                    # set alias for room, if provided
                    meetingUID = None
                    if 'meetingUID' in mDict:
                        meetingUID = mDict['meetingUID']
                        logger.debug("set meetingUID to {}...".format(meetingUID))
                    # set accessCode if provided
                    accessCode = None
                    if 'accessCode' in mDict:
                        accessCode = mDict['accessCode']
                        logger.debug("prepare accessCode")

                    # user exists (or was created) proceeding...
                    room_id = 0
                    # check if use homeroom
                    if 'useHomeRoom' in mDict and mDict['useHomeRoom'] == True:
                        room_id = gl.get_field_by_email(ownerEmail, 'room_id')
                        logger.debug("checking if home room exists...")
                        # create homeroom if not existing
                        if not room_id:
                            room_id = gl.create_room(ownerEmail, meetingName, meetingUID, None, None, None, None, accessCode)
                            if room_id > 0:
                                logger.debug("assigning home room {} to {}...".format(room_id, ownerEmail))
                                res = gl.update_field('users', 'email', ownerEmail, 'room_id', room_id)
                                if res == 0:
                                    logger.error("could not assign home room to user {} ".format(ownerEmail))
                            else:
                                logger.error("home room for user {} could not be created".format(ownerEmail))
                        if room_id > 0:
                            meetingUID = gl.get_table_field('rooms', 'id', room_id, 'uid')
                            logger.debug("using home room {} ({})".format(room_id, meetingUID))
                        else:
                            logger.error("home room {} cannot be used".format(ownerEmail))
                            sl.set_status(meeting, ['status'], '404', 'home room could not be used')
                            continue
                    # not using homeroom, check if roomID exists else create ...
                    # else create room 
                    elif meetingUID:
                        #check if meetingUID exists and fetch room_id
                        room_id = gl.get_table_field('rooms', 'uid', meetingUID, 'id')
                        if room_id:
                            logger.debug("set roomID to {} ({} - not using homeroom ...".format(room_id, meetingUID))
                        else:
                            res = gl.create_room(ownerEmail, meetingName, meetingUID, None, None, None, None, accessCode)
                            if res > 0:
                                room_id = gl.get_table_field('rooms', 'uid', meetingUID, 'id')
                            else:
                                logger.error("room for {} could not be created".format(meetingName))
                                sl.set_status(meeting, ['status'], '401', 'room could not be created')
                                continue
                    #get room info / join urls 
                    if room_id >0:
                        #a room for the meeting does exist
                        # execute all tasks for this meeting on this level (sharing, reminding, starting...
                        room_data = gl.table_row_as_dict('rooms', 'id', room_id, gl.roomsTableList)
                        # set room config (name, uid, accessCode,...
                        if meetingName:
                            gl.update_field('rooms', 'id', room_data['id'], 'name', meetingName)
                        if meetingUID:
                            gl.update_field('rooms', 'id', room_data['id'], 'uid', meetingUID)
                        if accessCode:
                            gl.update_field('rooms', 'id', room_data['id'], 'access_code', accessCode)
                        if meetingID:
                            gl.update_field('rooms', 'id', room_data['id'], 'bbb_id', meetingID)
                        meetingID = room_data['bbb_id']
                        # create meetingLink
                        meetingLink = "{}/{}".format(servers[server]['link_base'], room_data['uid'])
                        #create moderatorLink
                        moderatorLink = sl.get_join_url(room_data['bbb_id'], 'Moderator', 'moderator', room_data['moderator_pw'])
                        #set additional meeting properties
                        muteOnStart = None
                        if 'muteOnStart' in mDict:
                            muteOnStart = mDict['muteOnStart']
                        welcome = None
                        if 'welcome' in mDict:
                            welcome = mDict['welcome']
                            if 'startDate' in mDict:
                                welcome = welcome.replace('__startDate__', mDict['startDate'])
                        bannerText = None
                        if 'bannerText' in mDict:
                            bannerText = mDict['bannerText']
                            if 'startDate' in mDict:
                                bannerText = bannerText.replace('__startDate__', mDict['startDate'])
                        maxParticipants = None
                        if 'maxParticipants' in mDict:
                            maxParticipants = mDict['maxParticipants']
                        logoutURL = None
                        if 'logoutURL' in mDict:
                            logoutURL = mDict['logoutURL']
                        record = None
                        if 'record' in mDict:
                            record = mDict['record']
                        duration = None
                        if 'duration' in mDict:
                            duration = mDict['duration']
                        autoStartRecording = None
                        if 'autoStartRecording' in mDict:
                            autoStartRecording = mDict['autoStartRecording']
                        allowStartStopRecording = None
                        if 'allowStartStopRecording' in mDict:
                            allowStartStopRecording = mDict['allowStartStopRecording']
                        # correct startDate with preSTartMinutes
                        preStartMinutes = int(args.pre_start)
                        if 'preStartMinutes' in mDict:
                            preStartMinutes = mDict['preStartMinutes']
                        minutesLeft = 0
                        if 'startDate' in mDict:
                            td = sl.get_date(mDict['startDate']) - NOW
                            minutesLeft = int(td.total_seconds()/60)

                        # check status of meeting 
                        # if not 220 started yet
                        if sl.get_status(meeting, ['status']) != '220':
                            # check if startdate is set and reached...
                            # if no startdate was provided, start now
                            if not 'startDate' in mDict:
                                res = sl.start_meeting(room_data['bbb_id'], meetingName, room_data['moderator_pw'], room_data['attendee_pw'], muteOnStart, welcome, bannerText, maxParticipants, logoutURL, record, duration, autoStartRecording, allowStartStopRecording)
                                # set status: 0 failed - keep trying. 2 started - no users have joined, keep open. 1 started and users joined - stop processing
                                if res == 1:
                                    logger.info("started meeting {} - users have joined".format(meetingName))
                                    status = 'started'
                                    sl.set_status(meeting, ['status'],  '220', 'meeting started, users joined')
                                elif res == 2:
                                    logger.info("started meeting {} - no users have joined yet".format(meetingName))
                                    status = 'started'
                                    sl.set_status(meeting, ['status'],  '210', 'meeting started, no users joined')
                                elif res == 0:
                                    logger.error("meeting {} could not be started - trying again...".format(meetingName))
                                    sl.set_status(meeting, ['status'],  '400', 'meeting could not be started')
                            # if startdate set and now > startdate - preStartMinutes start meeting
                            elif minutesLeft - preStartMinutes <= 0:
                                logger.info("starting meeting {} now! Startdate: {}".format(meetingName, mDict['startDate']))
                                res = sl.start_meeting(room_data['bbb_id'], meetingName, room_data['moderator_pw'], room_data['attendee_pw'], muteOnStart, welcome, bannerText, maxParticipants, logoutURL, record, duration, autoStartRecording, allowStartStopRecording)
                                if res == 1:
                                    logger.info("started meeting {} - users have joined".format(meetingName))
                                    status = "started"
                                    sl.set_status(meeting, ['status'], '220', 'meeting started, users joined')
                                elif res == 2:
                                    logger.info("started meeting {} - no users have joined yet".format(meetingName))
                                    status = "started"
                                    sl.set_status(meeting, ['status'], '210', 'meeting started, no users joined yet')
                                elif res == 0:
                                    logger.error("meeting {} could not be started - trying again...".format(meetingName))
                                    sl.set_status(meeting, ['status'], '400', 'meeting could not be started')
                            else:
                                # check if room is to be preopened and
                                # keep open or wait...
                                preOpenMinutes = int(args.pre_open)
                                if 'preOpenMinutes' in mDict:
                                    preOpenMinutes  = mDict['preOpenMinutes']
                                preOpenMinutes   = preOpenMinutes + preStartMinutes
                                # if minutes left - pre open minutes <= now
                                if minutesLeft - preOpenMinutes <= 0:
                                    # check if preopenstatus not 220
                                    if sl.get_status(meeting, ['preOpen']) != '220':
                                        res = sl.end_meeting(room_data['bbb_id'])
                                        # if res 1 set preopenstatus 220
                                        if res == 1:
                                            time.sleep(4)
                                            if sl.meeting_info(room_data['bbb_id']) == 0:
                                                logger.info("closed meeting to reset parameters for reopening")
                                                sl.set_status(meeting, ['preOpen'], '220', 'closed meeting to reset parameters for reopening')
                                            else:
                                                logger.error("meeting could not be closed")
                                                sl.set_status(meeting, ['preOpen'], '420', 'could not close meeting for preOpening')
                                        else:
                                            logger.info("meeting was not running")
                                            sl.set_status(meeting, ['preOpen'], '220', 'meeting was not running')

                                    # open room
                                    res = sl.start_meeting(room_data['bbb_id'], meetingName, room_data['moderator_pw'], room_data['attendee_pw'], muteOnStart, welcome, bannerText, maxParticipants, logoutURL, record, duration, autoStartRecording, allowStartStopRecording)
                                    if res == 1:
                                        logger.info("opened meeting {} - users have joined".format(meetingName))
                                        sl.set_status(meeting, ['preOpen'], '220', 'meeting opened, users joined')
                                    elif res == 2:
                                        logger.info("opened meeting {} - no users have joined yet".format(meetingName))
                                        sl.set_status(meeting, ['preOpen'], '220', 'meeting opened, no users joined yet')
                                    elif res == 0:
                                        logger.error("meeting {} could not be pre opened - trying again...".format(meetingName))
                                        sl.set_status(meeting, ['preOpen'], '400', 'meeting could not be started')

                                logger.info("waiting for startDate of meeting {} - startdate: {} (starting in {} minutes). Opening room in {} minutes.".format(meetingName, mDict['startDate'], minutesLeft - preStartMinutes, minutesLeft - preOpenMinutes))
                                sl.set_status(meeting, ['status'], '201', 'waiting for startDate {}'.format(mDict['startDate']))
                        # 
                        # if endAfterMinutes is set, close meeting when time is passed
                        endAfterMinutes = int(args.end_after)
                        if 'endAfterMinutes' in mDict:
                            endAfterMinutes = mDict['endAfterMinutes']
                        minutesPassed = 0
                        if 'startDate' in mDict:
                            td = NOW - sl.get_date(mDict['startDate'])
                            minutesPassed = int(td.total_seconds()/60)
                        if minutesPassed > 0 and endAfterMinutes > 0:
                            if minutesPassed < endAfterMinutes:
                                logger.info("closing meeting {} in {} minutes".format(mDict['meetingName'], endAfterMinutes - minutesPassed))
                            if minutesPassed >= endAfterMinutes:
                                # check if endStatus not 220
                                if sl.get_status(meeting, ['endMeeting']) != '220':
                                    res = sl.end_meeting(room_data['bbb_id'])
                                    # if res 1 set preopenstatus 220
                                    if res == 1:
                                        time.sleep(4)
                                        if sl.meeting_info(room_data['bbb_id']) == 0:
                                            logger.info("closed meeting after {} minutes".format(endAfterMinutes))
                                            sl.set_status(meeting, ['endMeeting'], '220', 'closed meeting')
                                        else:
                                            logger.error("meeting could not be closed")
                                            sl.set_status(meeting, ['endMeeting'], '420', 'could not close meeting')
                                    else:
                                        logger.info("meeting was not running")
                                        sl.set_status(meeting, ['endMeeting'], '220', 'meeting was not running')
                                    logger.info("mark meeting {} as finished".format(mDict['meetingName']))
                                    sl.set_status(meeting, ['status'], '220', 'meeting has finished and was closed')

                        #
                        # meeting processed - handle other tasks and mails...
                        # aktivate liveStreaming if configured
                        # 
                        if 'liveStreaming' in mDict:
                            # check if all required parameters are given
                            liveStreaming = mDict['liveStreaming']
                            if 'targetUrl' in liveStreaming and 'streamerHost' in liveStreaming:
                                targetUrl = liveStreaming['targetUrl']
                                streamerHost = liveStreaming['streamerHost']
                                playIntro = ""
                                if 'playIntro' in liveStreaming:
                                    playIntro = liveStreaming['playIntro']

                                #parameters are available check if streaming has to be started
                                logger.debug("liveStreaming configured - check wether to start or not...")
                                if sl.get_status(meeting, ['liveStreaming']) != '220':
                                    # start livestreaming ... if meeting is running
                                    if sl.get_status(meeting, ['status']) == '220':
                                        # end old livestream on the host of the streamer...
                                        logger.info("end existing liveStream on host {}".format(streamerHost))
                                        logger.info("starting liveStream to {}".format(targetUrl))
                                        try:
                                            sshRes = subprocess.run('ssh root@{} "cd;cd BigBlueButton-liveStreaming;docker-compose down"'.format(streamerHost), shell=True, stdout=subprocess.DEVNULL).returncode
                                        except subprocess.CalledProcessError as ERR:
                                            logger.error(ERR)
                                            sshRes = 1
                                        if sshRes == 0:
                                            sl.set_status(meeting, ['liveStreaming'], '210', 'old liveStreaming stopped!')

                                        # now start the stream on the host
                                        bbbIntroFlag = ""
                                        if playIntro:
                                            bbbIntroFlag = 'BBB_INTRO=\"{}\"'.format(playIntro) 
                                        logger.info("starting liveStream to {}".format(targetUrl))
                                        try:
                                            sshRes= subprocess.run('ssh root@{} bash -c "\'cd; cd BigBlueButton-liveStreaming; BBB_URL=\"{}\" BBB_SECRET=\"{}\" BBB_MEETING_ID=\"{}\" BBB_STREAM_URL=\"{}\" {} docker-compose up -d;\'"'.format(streamerHost, servers[server]['BBB_URL'], servers[server]['BBB_SECRET'], meetingID, targetUrl, bbbIntroFlag), shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
                                        except subprocess.CalledProcessError as ERR:
                                            logger.error(ERR)
                                            sl.set_status(meeting, ['liveStreaming'], '400', 'liveStreaming failed!')
                                        if sshRes.returncode == 0:
                                            logger.info("started liveStream for {} {} ({})".format(meetingID, playIntro, sshRes.stdout))
                                            logger.info("command: {}".format(sshRes.args))
                                            sl.set_status(meeting, ['liveStreaming'], '220', 'liveStreaming started!')
                                        else:
                                            logger.error('command to start liveStreaming failed: {}'.format(sshRes.stdout))
                                            sl.set_status(meeting, ['liveStreaming'], '400', 'liveStreaming failed!')

                                    else:
                                        logger.info("liveStreaming waiting for meeting to start")
                                        #sl.set_status(meeting, ['liveStreaming'], '210', 'waiting for liveStreaming slot...')
                                else:
                                    logger.debug("liveStreaming already started")
                            else:
                                logger.error("liveStreaming not correctly configured")

                        # Mail handling
                        # mail server configs
                        mail_properties = {}
                        mail_properties['mailServer'] = servers[server]['mailServer']
                        mail_properties['mailUser'] = servers[server]['mailUser']
                        mail_properties['mailPassword'] = servers[server]['mailPassword']
                        # send owner email with infos / links
                        # if  not 250 owner info mail sent
                        if sl.get_status(meeting, ['owner', 'infoMailSent']) != '250':
                            # sender and receiver
                            # set mailFrom as required but override if provided on server or meeting basis
                            mail_properties['mailFrom'] = ownerEmail
                            if 'mailFrom' in servers[server]:
                                mail_properties['mailFrom'] = servers[server]['mailFrom']
                            if 'mailFrom' in mDict:
                                mail_properties['mailFrom'] = mDict['mailFrom']
                            # set mailFromName as required but override if provided on server or meeting basis
                            mail_properties['mailFromName'] = ownerFullName
                            if 'mailFromName' in servers[server]:
                                mail_properties['mailFromName'] = servers[server]['mailFromName']
                            if 'mailFromName' in mDict:
                                mail_properties['mailFromName'] = mDict['mailFromName']
                            # set mailTo as required but override if provided on server or meeting basis
                            mail_properties['mailTo'] = ownerEmail
                            if 'mailTo' in servers[server]:
                                mail_properties['mailTo'] = servers[server]['mailTo']
                            if 'mailTo' in mDict:
                                mail_properties['mailTo'] = mDict['mailTo']
                            # set mailToName as required but override if provided on server or meeting basis
                            mail_properties['mailToName'] = ownerFullName
                            if 'mailToName' in servers[server]:
                                mail_properties['mailToName'] = servers[server]['mailToName']
                            if 'mailToName' in mDict:
                                mail_properties['mailToName'] = mDict['mailToName']
                            # template to use
                            mailTemplate = "meetingOwnerInfoTemplate.j2"
                            if 'meetingOwnerInfoTemplate' in mDict:
                                mailTemplate = mDict['meetingOwnerInfoTemplate']
                            mail_properties['mailText'] = sl.render_template(mailTemplate, vars=locals())
                            try:
                                res = sl.r.xadd('mailStream', { meeting: json.dumps(mail_properties) })
                                logger.debug("send owner info mail with template {}".format(mailTemplate))
                                sl.set_status(meeting, ['owner', 'infoMailSent'], '250', 'sent owner info mail')
                            except Exception as ERR:
                                logger.error("failed to send owner info mail for {} to queue. {}".format(meetingName, ERR))
                                sl.set_status(meeting, ['owner', 'infoMailSent'],  '550', 'sending mail failed')
                        # send started mail if status 210 or 220 
                        # if  not 250 owner start mail sent
                        if sl.get_status(meeting, ['owner', 'startMailSent']) != '250':
                            if sl.get_status(meeting, ['status']) == '220' or sl.get_status(meeting, ['status']) == '210':
                                # set mailFrom as required but override if provided on server or meeting basis
                                mail_properties['mailFrom'] = ownerEmail
                                if 'mailFrom' in servers[server]:
                                    mail_properties['mailFrom'] = servers[server]['mailFrom']
                                if 'mailFrom' in mDict:
                                    mail_properties['mailFrom'] = mDict['mailFrom']
                                # set mailFromName as required but override if provided on server or meeting basis
                                mail_properties['mailFromName'] = ownerFullName
                                if 'mailFromName' in servers[server]:
                                    mail_properties['mailFromName'] = servers[server]['mailFromName']
                                if 'mailFromName' in mDict:
                                    mail_properties['mailFromName'] = mDict['mailFromName']
                                # set mailTo as required but override if provided on server or meeting basis
                                mail_properties['mailTo'] = ownerEmail
                                if 'mailTo' in servers[server]:
                                    mail_properties['mailTo'] = servers[server]['mailTo']
                                if 'mailTo' in mDict:
                                    mail_properties['mailTo'] = mDict['mailTo']
                                # set mailToName as required but override if provided on server or meeting basis
                                mail_properties['mailToName'] = ownerFullName
                                if 'mailToName' in servers[server]:
                                    mail_properties['mailToName'] = servers[server]['mailToName']
                                if 'mailToName' in mDict:
                                    mail_properties['mailToName'] = mDict['mailToName']
                                # template to use
                                mailTemplate = "meetingOwnerStartedTemplate.j2"
                                if 'meetingOwnerStartedTemplate' in mDict:
                                    mailTemplate = mDict['meetingOwnerStartedTemplate']
                                mail_properties['mailText'] = sl.render_template(mailTemplate, vars=locals())
                                try:
                                    res = sl.r.xadd('mailStream', { meeting: json.dumps(mail_properties) })
                                    # set status to sent owner mail
                                    logger.debug("sent owner started mail with template {}".format(mailTemplate))
                                    sl.set_status(meeting, ['owner', 'startMailSent'], '250', 'sent owner start mail')
                                except Exception as ERR:
                                    logger.debug("failed to send owner started mail with template {}. {}".format(mailTemplate, ERR))
                                    sl.set_status(meeting, ['owner', 'startMailSent'], '550', 'sending mail failed')
                        # handle reminder
                        # if startDate set and ( args.reminder_minutes set or mdict['reminder'] ) and now > startDate reminder meeting - reminder (in minutes)
                        # if meeting has no users joined
                        if sl.get_status(meeting, ['status']) != '220':
                            reminderMinutes =  0
                            if args.reminder_minutes:
                                reminderMinutes = int(args.reminder_minutes)
                            if 'reminderMinutes' in mDict:
                                reminderMinutes = mDict['reminderMinutes']
                            if 'startDate' in mDict and reminderMinutes > 0:
                                if minutesLeft - preStartMinutes - reminderMinutes > 0:
                                    logger.debug("meeting {} starting at {} - reminding in {} minutes!".format(meetingName, mDict['startDate'], int(minutesLeft - reminderMinutes - preStartMinutes)))
                                elif minutesLeft - preStartMinutes > 0:
                                    logger.debug("reminding of meeting {} now!".format(meetingName))
                                    # send reminder mail
                                    # if  not 250 owner reminder mail sent
                                    if sl.get_status(meeting, ['owner', 'reminderMailSent']) != '250':
                                        # sender and receiver
                                        # set mailFrom as required but override if provided on server or meeting basis
                                        mail_properties['mailFrom'] = ownerEmail
                                        if 'mailFrom' in servers[server]:
                                            mail_properties['mailFrom'] = servers[server]['mailFrom']
                                        if 'mailFrom' in mDict:
                                            mail_properties['mailFrom'] = mDict['mailFrom']
                                        # set mailFromName as required but override if provided on server or meeting basis
                                        mail_properties['mailFromName'] = ownerFullName
                                        if 'mailFromName' in servers[server]:
                                            mail_properties['mailFromName'] = servers[server]['mailFromName']
                                        if 'mailFromName' in mDict:
                                            mail_properties['mailFromName'] = mDict['mailFromName']
                                        # set mailTo as required but override if provided on server or meeting basis
                                        mail_properties['mailTo'] = ownerEmail
                                        if 'mailTo' in servers[server]:
                                            mail_properties['mailTo'] = servers[server]['mailTo']
                                        if 'mailTo' in mDict:
                                            mail_properties['mailTo'] = mDict['mailTo']
                                        # set mailToName as required but override if provided on server or meeting basis
                                        mail_properties['mailToName'] = ownerFullName
                                        if 'mailToName' in servers[server]:
                                            mail_properties['mailToName'] = servers[server]['mailToName']
                                        if 'mailToName' in mDict:
                                            mail_properties['mailToName'] = mDict['mailToName']
                                        # template to use
                                        mailTemplate = "meetingOwnerReminderTemplate.j2"
                                        if 'meetingOwnerReminderTemplate' in mDict:
                                            mailTemplate = mDict['meetingOwnerReminderTemplate']
                                        mail_properties['mailText'] = sl.render_template(mailTemplate, vars=locals())
                                        try:
                                            res = sl.r.xadd('mailStream', { meeting: json.dumps(mail_properties) })
                                            # set status to sent owner mail
                                            logger.debug("sent owner reminder mail with template {}".format(mailTemplate))
                                            sl.set_status(meeting, ['owner', 'reminderMailSent'], '250', 'sent owner reminder mail')
                                        except Exception as ERR:
                                            logger.debug("failed to send owner reminder mail with template {}. {}".format(mailTemplate, ERR))
                                            sl.set_status(meeting, ['owner', 'reminderMailSent'], '550', 'sending mail failed')
                        #
                        # check if share_with was provided containing email -> fullName otherwise fail
                        #todo: remove continue replace with if else
                        if 'shareWith' in mDict:
                            if isinstance(mDict['shareWith'], dict):
                                for email in mDict['shareWith']:
                                    send_emails = meeting_send_emails
                                    if 'send_emails' in mDict['shareWith'][email]:
                                        send_emails = mDict['shareWith'][email]['send_emails']
                                    logger.debug("sharing room with {}".format(email))
                                    if sl.get_status(meeting, ['shareWith', email]) != '220':
                                        if 'fullName' in mDict['shareWith'][email]:
                                            fullName = mDict['shareWith'][email]['fullName']
                                        else:
                                            fullName = email.partition('@')[0]
                                        res = gl.share_room(room_id, email)
                                        if res > 0:
                                            logger.debug("shared room {} with {}".format(room_id, email))
                                            sl.set_status(meeting, ['shareWith', email], '220', 'room shared')
                                    else:
                                        logger.debug("room already shared {} with {}".format(room_id, email))
                                    # send share mail
                                    if sl.get_status(meeting, ['shareWith', email, 'sendShareMail']) != '250':
                                        # mail server configs
                                        mail_properties = {}
                                        mail_properties['mailServer'] = servers[server]['mailServer']
                                        mail_properties['mailUser'] = servers[server]['mailUser']
                                        mail_properties['mailPassword'] = servers[server]['mailPassword']
                                        # sender and receiver
                                        # set mailFrom as required but override if provided on server or meeting basis
                                        mail_properties['mailFrom'] = ownerEmail
                                        if 'mailFrom' in servers[server]:
                                            mail_properties['mailFrom'] = servers[server]['mailFrom']
                                        if 'mailFrom' in mDict:
                                            mail_properties['mailFrom'] = mDict['mailFrom']
                                        # set mailFromName as required but override if provided on server or meeting basis
                                        mail_properties['mailFromName'] = ownerFullName
                                        if 'mailFromName' in servers[server]:
                                            mail_properties['mailFromName'] = servers[server]['mailFromName']
                                        if 'mailFromName' in mDict:
                                            mail_properties['mailFromName'] = mDict['mailFromName']
                                        # set mailTo as required but override if provided on server or meeting basis
                                        mail_properties['mailTo'] = email
                                        if 'mailTo' in servers[server]:
                                            mail_properties['mailTo'] = servers[server]['mailTo']
                                        if 'mailTo' in mDict:
                                            mail_properties['mailTo'] = mDict['mailTo']
                                        # set mailToName as required but override if provided on server or meeting basis
                                        mail_properties['mailToName'] = fullName
                                        if 'mailToName' in servers[server]:
                                            mail_properties['mailToName'] = servers[server]['mailToName']
                                        if 'mailToName' in mDict:
                                            mail_properties['mailToName'] = mDict['mailToName']
                                        # template to use
                                        mailTemplate = "meetingShareInfoTemplate.j2"
                                        if 'meetingShareInfoTemplate' in mDict:
                                            mailTemplate = mDict['meetingShareInfoTemplate']
                                        mail_properties['mailText'] = sl.render_template(mailTemplate, vars=locals())
                                        try:
                                            res = sl.r.xadd('mailStream', { meeting: json.dumps(mail_properties) })
                                            logger.debug("sent share mail with template {}".format(mailTemplate))
                                            sl.set_status(meeting, ['shareWith', email, 'sendShareMail'], '250', 'sent mail')
                                        except Exception as ERR:
                                            logger.error("could not send share mail with template {}. {}".format(mailTemplate, ERR))
                                            sl.set_status(meeting, ['shareWith', email, 'sendShareMail'], '440', 'could not send share mail')

                        #        sendInvitationLink:
                        if 'sendInvitationLink' in mDict:
                            if isinstance(mDict['sendInvitationLink'], dict):
                                for email in mDict['sendInvitationLink']:
                                    # get status
                                    if sl.get_status(meeting, ['sendInvitationLink', email]) == '250':
                                        logger.debug("invitation to {} already sent".format(email))
                                        continue 

                                    # prepare and send mail
                                    if 'fullName' in mDict['sendInvitationLink'][email]:
                                        fullName = mDict['sendInvitationLink'][email]['fullName']
                                    else:
                                        fullName = email.partition('@')[0]
                                    # mail server configs
                                    mail_properties = {}
                                    mail_properties['mailServer'] = servers[server]['mailServer']
                                    mail_properties['mailUser'] = servers[server]['mailUser']
                                    mail_properties['mailPassword'] = servers[server]['mailPassword']
                                    # sender and receiver
                                    # set mailFrom as required but override if provided on server or meeting basis
                                    mail_properties['mailFrom'] = ownerEmail
                                    if 'mailFrom' in servers[server]:
                                        mail_properties['mailFrom'] = servers[server]['mailFrom']
                                    if 'mailFrom' in mDict:
                                        mail_properties['mailFrom'] = mDict['mailFrom']
                                    # set mailFromName as required but override if provided on server or meeting basis
                                    mail_properties['mailFromName'] = ownerFullName
                                    if 'mailFromName' in servers[server]:
                                        mail_properties['mailFromName'] = servers[server]['mailFromName']
                                    if 'mailFromName' in mDict:
                                        mail_properties['mailFromName'] = mDict['mailFromName']
                                    # set mailTo as required but override if provided on server or meeting basis
                                    mail_properties['mailTo'] = email
                                    if 'mailTo' in servers[server]:
                                        mail_properties['mailTo'] = servers[server]['mailTo']
                                    if 'mailTo' in mDict:
                                        mail_properties['mailTo'] = mDict['mailTo']
                                    # set mailToName as required but override if provided on server or meeting basis
                                    mail_properties['mailToName'] = fullName
                                    if 'mailToName' in servers[server]:
                                        mail_properties['mailToName'] = servers[server]['mailToName']
                                    if 'mailToName' in mDict:
                                        mail_properties['mailToName'] = mDict['mailToName']
                                    # template to use
                                    mailTemplate = "meetingInvitationInfoTemplate.j2"
                                    if 'meetingInvitationInfoTemplate' in mDict:
                                        mailTemplate = mDict['meetingInvitationInfoTemplate']
                                    mail_properties['mailText'] = sl.render_template(mailTemplate, vars=locals())
                                    try:
                                        res = sl.r.xadd('mailStream', { meeting: json.dumps(mail_properties) })
                                        logger.debug("invitation to {} sent".format(email))
                                        sl.set_status(meeting, ['sendInvitationLink', email], '250', 'invitation mail sent')
                                    except Exception as ERR:
                                        logger.error("invitation to {} could not be send. {}".format(email, ERR))
                                        sl.set_status(meeting, ['sendInvitationLink', email], '550', 'invitation mail could not be send')

                        #        sendModeratorLink:
                        if 'sendModeratorLink' in mDict:
                            if isinstance(mDict['sendModeratorLink'], dict):
                                for email in mDict['sendModeratorLink']:
                                    send_emails = meeting_send_emails
                                    if 'send_emails' in mDict['sendModeratorLink'][email]:
                                        send_emails = mDict['sendModeratorLink'][email]['send_emails']
                                    if sl.get_status(meeting, ['sendModeratorLink', email]) == '250':
                                        logger.debug("moderator link already sent")
                                        continue
                                    if 'fullName' in mDict['sendModeratorLink'][email]:
                                        fullName = mDict['sendModeratorLink'][email]['fullName']
                                    else:
                                        fullName = email.partition('@')[0]
                                    moderatorLink = sl.get_join_url(room_data['bbb_id'], fullName, 'moderator', room_data['moderator_pw'])
                                    if moderatorLink:
                                        # mail server configs
                                        mail_properties = {}
                                        mail_properties['mailServer'] = servers[server]['mailServer']
                                        mail_properties['mailUser'] = servers[server]['mailUser']
                                        mail_properties['mailPassword'] = servers[server]['mailPassword']
                                        # sender and receiver
                                        # set mailFrom as required but override if provided on server or meeting basis
                                        mail_properties['mailFrom'] = ownerEmail
                                        if 'mailFrom' in servers[server]:
                                            mail_properties['mailFrom'] = servers[server]['mailFrom']
                                        if 'mailFrom' in mDict:
                                            mail_properties['mailFrom'] = mDict['mailFrom']
                                        # set mailFromName as required but override if provided on server or meeting basis
                                        mail_properties['mailFromName'] = ownerFullName
                                        if 'mailFromName' in servers[server]:
                                            mail_properties['mailFromName'] = servers[server]['mailFromName']
                                        if 'mailFromName' in mDict:
                                            mail_properties['mailFromName'] = mDict['mailFromName']
                                        # set mailTo as required but override if provided on server or meeting basis
                                        mail_properties['mailTo'] = email
                                        if 'mailTo' in servers[server]:
                                            mail_properties['mailTo'] = servers[server]['mailTo']
                                        if 'mailTo' in mDict:
                                            mail_properties['mailTo'] = mDict['mailTo']
                                        # set mailToName as required but override if provided on server or meeting basis
                                        mail_properties['mailToName'] = fullName
                                        if 'mailToName' in servers[server]:
                                            mail_properties['mailToName'] = servers[server]['mailToName']
                                        if 'mailToName' in mDict:
                                            mail_properties['mailToName'] = mDict['mailToName']
                                        # template to use
                                        mailTemplate = "meetingModeratorInfoTemplate.j2"
                                        if 'meetingModeratorInfoTemplate' in mDict:
                                            mailTemplate = mDict['meetingModeratorInfoTemplate']
                                        mail_properties['mailText'] = sl.render_template(mailTemplate, vars=locals())
                                        try:
                                            res = sl.r.xadd('mailStream', { meeting: json.dumps(mail_properties) })
                                            logger.debug("sent moderator info mail with template {}".format(mailTemplate))
                                            sl.set_status(meeting, ['sendModeratorLink', email], '250', 'sent moderator info mail')
                                        except Exception as ERR:
                                            logger.error("could not send moderator info mail with template {}. {}".format(mailTemplate, ERR))
                                            sl.set_status(meeting, ['sendModeratorLink', email], '440', 'could not send moderator link')
                                    else:
                                        logger.debug("Could not create and send moderator link")
                                        sl.set_status(meeting, ['sendModeratorLink', email], '440', 'could not create moderator link')
                    else:
                        logger.error("no room available")
                        sl.set_status(meeting, ['status'], '404', 'no room available')
                else:
                    logger.error("Email missing. Provide one Owner with email and optional fullName")
                    sl.set_status(meeting, ['status'], '404', 'no owner email provided')
            else:
                logger.debug("No owner found. Provide one Owner with email and optional fullName")
                sl.set_status(meeting, ['status'], '404', 'no owner with email provided')

        # finally store processed meeting
        logger.debug("saving meeting...")
        logger.debug("saved meeting: {}".format(sl.r.set('meeting:{}'.format(meeting), json.dumps(mDict))))
        logger.debug("waiting...")
        time.sleep(0.1)

    # shut down
    time.sleep(1)
    if stop:
        logger.info("shutting down...")
        gl.close()
        sl.r.bgsave()
        sl.r.connection_pool.disconnect()
        break
