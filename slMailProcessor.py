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
import argparse, sys, os, logging, yaml, urllib, json
import redis
from datetime import datetime, timedelta
from socket import gethostbyname,gaierror 
import time
import signal
import random
import string
import smtplib

def get_date(dateString):
    format_string = "%Y-%m-%d %H:%M"
    return datetime.strptime(dateString, format_string)

def sigint_handler(sig, frame):
    logger.debug("received {}...".format(sig))
    global stop
    stop = True

def parseArgs():
    parser = argparse.ArgumentParser()
    parser.add_argument("-d","--debug_emails", help="print mails insttead of sending them", action="store_true")
    parser.add_argument("-n","--no_emails", help="prevent sending of emails", action="store_true")
    parser.add_argument("-g","--logFile", help="path to logFile in yaml format", default="./scheduLight.log")
    return parser.parse_args()

def config_exists(my_dict, my_list):
    for my_item in my_list:
        if my_item not in my_dict:
            return False
    return True

def send_email(mail_properties):
    if not config_exists(mail_properties,['mailServer', 'mailUser', 'mailPassword', 'mailFrom', 'mailFromName', 'mailTo', 'mailToName', 'mailText']):
        logger.error("MailServer not configured or parameters missing...")
        return 0
    if 'contentType' in mail_properties and mail_properties['contentType'] == 'plain':
        contentType = "Content-type: text/plain; charset=utf-8"
    else:
        contentType = "Content-type: text/html; charset=utf-8"

    mailText = '''From: "{}" <{}>
To: "{}" <{}>
MIME-Version: 1.0
{}
{}
    '''.format(mail_properties['mailFromName'], mail_properties['mailFrom'], mail_properties['mailToName'], mail_properties['mailTo'], contentType, mail_properties['mailText'])

    if args.no_emails == True:
        logger.debug("not sending emails to {} due to configuration...".format(mail_properties['mailTo']))
        if args.debug_emails == True:
            logger.debug(mailText)
        return 0

    try:
        server = smtplib.SMTP(mail_properties['mailServer'])
        server.starttls()
        server.login(mail_properties['mailUser'], mail_properties['mailPassword'])
        server.sendmail(mail_properties['mailFrom'], [mail_properties['mailTo']], mailText.encode('utf-8'))
        server.quit()
        return 1
    except Exception as ERR:
        logger.error("Error sending email: {}!".format(ERR))
        return 0
#########
### start ###
#parse the commandline arguments
args = parseArgs()
stop = False
# signal processing
signal.signal(signal.SIGTERM, sigint_handler)
signal.signal(signal.SIGINT, sigint_handler)

## create logger with 'setMeetings'
logger = logging.getLogger('mailProcessor')
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
logger.info("starting...")
# connect to redis db
r = redis.StrictRedis( host="localhost", port="6380", db=1, ssl=False, charset="utf-8", decode_responses=True)
try:
    r.info()
except redis.exceptions.ConnectionError as ERR:
    logger.error("Redis not ready: {}".format(ERR))
    sys.exit()
# run application 
while True:
    # set startTime
    NOW = datetime.now()
    logger.debug("Date: {}".format(NOW))
    # send mails fetched from stream:
    try:
        r.xreadgroup('mailNotifications', 'consumer1', { 'mailStream': '0' }, None, None, True)
    except redis.exceptions.ResponseError as ERR:
        logger.debug(ERR)
        break
    logger.debug("process old messages")
    for stream in r.xreadgroup('mailNotifications', 'consumer1', { 'mailStream': '0' }, None, None, False):
        logger.debug("Stream: {}".format(stream[0]))
        for msg in stream[1]:
            (id, item) = msg
            logger.debug("id: {}".format(id))
            logger.debug("item: {}".format(item))
            for key in item:
                mail_properties = json.loads(item[key])
            res = send_email(mail_properties)
            if res == 1:
                logger.info("send mail {} to {}".format(key, mail_properties['mailTo']))
                logger.debug("ack msg: {}".format(r.xack('mailStream', 'mailNotifications', id)))
            elif res == 0:
                logger.error("failed to send mail {} for {}".format(key, mail_properties['mailTo']))
            time.sleep(0.1)


    logger.debug("process new messages")
    for stream in r.xreadgroup('mailNotifications', 'consumer1', { 'mailStream': '>' }, None, None, False):
        logger.debug("Stream: {}".format(stream[0]))
        for msg in stream[1]:
            (id, item) = msg
            logger.debug("id: {}".format(id))
            for key in item:
                mail_properties = json.loads(item[key])
            res = send_email(mail_properties)
            if res == 1:
                logger.info("send mail {} to {}".format(key, mail_properties['mailTo']))
                logger.debug("ack msg: {}".format(r.xack('mailStream', 'mailNotifications', id)))
            elif res == 0:
                logger.error("failed to send mail {} for {}".format(key, mail_properties['mailTo']))
            time.sleep(0.1)



    # shut down
    time.sleep(1)
    if stop:
        logger.info("shutting down...")
        r.bgsave()
        r.connection_pool.disconnect()
        break
