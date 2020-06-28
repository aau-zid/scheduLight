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
import logging
import psycopg2
import uuid
import random
import string
import json
from datetime import datetime, timedelta

class greenLight:
    """ provides some methods to interact with greenlight """
    # set startTime
    NOW = datetime.now()
    # define the table structure of greenlight sql tables for compatibility checks
    usersTableList = ['id', 'room_id', 'provider', 'uid', 'name', 'username', 'email', 'social_uid', 'image', 'password_digest', 'accepted_terms', 'created_at', 'updated_at', 'email_verified', 'language', 'reset_digest', 'reset_sent_at', 'activation_digest', 'activated_at', 'deleted', 'role_id']
    roomsTableList = ['id', 'user_id', 'name', 'uid', 'bbb_id', 'sessions', 'last_session', 'created_at', 'updated_at', 'room_settings', 'moderator_pw', 'attendee_pw', 'access_code', 'deleted']
    sharedTableList = ['id', 'room_id', 'user_id', 'created_at', 'updated_at']

    def __init__(self, gl_dbName, gl_dbUser, gl_dbPassword, gl_dbHost, gl_dbPort, gl_logFile='greenLight.log'):
        ## create logger with 'greenLight'
        self.logger = logging.getLogger('greenLight')
        self.logger.setLevel(logging.DEBUG)
        ## create file handler which logs even debug messages
        fh = logging.handlers.RotatingFileHandler(gl_logFile, maxBytes=1000000, backupCount=5)
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
        self.logger.debug("starting...")
        # connect to greenlight database
        self.logger.debug("connecting to database...")
        self.con = psycopg2.connect(database=gl_dbName, user=gl_dbUser, password=gl_dbPassword, host=gl_dbHost, port=gl_dbPort)
        self.cur = self.con.cursor()
        # check greenlight database compatibility
        self.logger.debug("check database compatibility...")
        self.check_compatibility()

    def check_compatibility(self):
        # check users table
        if self.usersTableList != self.table_as_list('users'):
            self.logger.error("users table has changed, please update!")
            sys.exit()
        # check rooms table
        if self.roomsTableList != self.table_as_list('rooms'):
            self.logger.error("rooms table has changed, please update!")
            sys.exit()
        # check shared_accesses table
        if self.sharedTableList != self.table_as_list('shared_accesses'):
            self.logger.error("shared_accesses table has changed, please update!")
            sys.exit()
    
    def table_as_list(self, table):
        # list table columns as list
        sql = "SELECT column_name FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = '{}';".format(table)
        self.cur.execute(sql)
        tableRows = []
        for field in self.cur.fetchall():
            tableRows.append(field[0])
        return tableRows
    
    def user_role(self, email, role=1):
        sql = "Update users set role_id = %s where email = %s;"
        data = (role, email, )
        self.cur.execute(sql, data) 
        self.con.commit() 
        return self.cur.rowcount
    
    def update_field(self, table, update_by, user_id, field, value):
        sql = "Update {} set {} = %s where {} = %s;".format(table, field, update_by)
        data = (value, user_id)
        self.cur.execute(sql, data) 
        self.con.commit() 
        return self.cur.rowcount
    
    def delete_user(self, user_id, delete_by='email'):
        user_id = self.get_table_field('users', delete_by, user_id, 'id')
        sql = "DELETE from users WHERE  id= '{}';".format(user_id)
        self.cur.execute(sql)
        self.con.commit() # <- We MUST commit to reflect the deleted data
        res = self.cur.rowcount
        if res > 0:
            self.logger.debug("deleted user {}".format(user_id))
            sql = "DELETE from users_roles WHERE user_id = '{}';".format(user_id)
            self.cur.execute(sql)
            self.con.commit() # <- We MUST commit to reflect the deleted data
            res2 = self.cur.rowcount
            if res2 > 0:
                self.logger.debug("deleted user roles of {}".format(user_id))
            else:
                self.logger.debug("no user roles of {}".format(user_id))
            self.logger.debug("deleting rooms of user {}".format(user_id))
            sql = "SELECT id from rooms where user_id = '{}';".format(user_id)
            tableRows = []
            self.cur.execute(sql)
            for field in self.cur.fetchall():
                tableRows.append(field[0])
            for room in tableRows:
                self.delete_room(room, 'id')
        return res
    
    def create_user(self, email, fullName=None, uid=None, social_uid=None, password=None, role_id=1, provider='ldap'):
        if self.get_table_field('users', 'email', email, 'id'):
            self.logger.error("email {} does already exist. Could not create user {}.".format(email, fullName))
            return 0
        if not password:
            self.logger.debug("creating pwd...")
            password = self.random_secret()
        if not fullName:
            self.logger.debug("creating fullName from email...")
            fullName = email.partition('@')[0]
        if not uid:
            self.logger.debug("creating uid...")
            uid = "sl-{}".format(self.random_secret())
        sql = "INSERT INTO users (room_id, provider, uid, name, username, email, social_uid, image, password_digest, accepted_terms, created_at, updated_at, email_verified, language, reset_digest, reset_sent_at, activation_digest, activated_at, deleted, role_id) VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;"
        data = (None, provider, uid, fullName, uid, email, social_uid, None, password, True, self.NOW, self.NOW, True, None, None, None, None, self.NOW, False, role_id)
        self.cur.execute(sql, data) 
        self.con.commit() 
        id = self.cur.fetchone()[0]
        if id:
            return 1
        else:
            self.logger.error("user {} could not be created: {}".format(email, id))
            return 0
        # create via rake: res= subprocess.check_output('docker exec greenlight-v2 bundle exec rake user:create["{}","{}","{}","{}","{}"]'.format(user, email, password, role, provider), shell=True).decode('utf-8')
        #if res.startswith("Account succes"):
            # bugfix (default role not set on create)
            # fixed in 2.6.2         res2 = self.user_role(email, 1)
    
    def create_room(self, email, meetingName=None, meetingUID=None, room_settings=None, bbb_id=None, attendeePW=None, moderatorPW=None, accessCode=None):
        user_id = self.get_id_by_email(email)
        if not user_id:
            self.logger.error("user {} does not exist. Could not create room {} for this user.".format(email, meetingName))
            return 0
        if not meetingName:
            meetingName = email
        if not bbb_id:
            self.logger.debug("creating bbb meetingID...")
            bbb_id =  uuid.uuid4().hex
        if not meetingUID:
            self.logger.debug("creating room alias...")
            meetingUID = self.random_secret()
        if self.get_table_field('rooms', 'uid', meetingUID, 'id'):
            self.logger.error("room {} does already exist. Could not create room {}.".format(meetingUID, meetingName))
            return 0

        if not attendeePW:
            self.logger.debug("creating attendee pwd...")
            attendeePW = self.random_secret()
        if not moderatorPW:
            self.logger.debug("creating moderator pwd...")
            moderatorPW = self.random_secret()
        if not room_settings:
            #room_settings = {"muteOnStart":true,"requireModeratorApproval":false,"anyoneCanStart":true,"joinModerator":true}
            self.logger.debug("creating room settings...")
            room_settings = {"muteOnStart":True,"requireModeratorApproval":False,"anyoneCanStart":False,"joinModerator":False}
            room_settings = json.dumps(room_settings)
    
        sql = "INSERT INTO rooms (user_id, name, uid, bbb_id, sessions, last_session, created_at, updated_at, room_settings, moderator_pw, attendee_pw, access_code, deleted) VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;"
        data = (user_id, meetingName, meetingUID, bbb_id, 0, None, self.NOW, self.NOW, room_settings, moderatorPW, attendeePW, accessCode, False)
        self.cur.execute(sql, data) 
        self.con.commit() 
        return self.cur.fetchone()[0]
    
    def rename_room(self, old_value, new_value, rename_by='uid'):
        if rename_by not in ['uid', 'name']:
            self.logger.error("renaming rooms is only allowed by uid or name. given: {}".format(rename_by))
            return 0
        sql = "Update rooms set {} = %s where {} = %s".format(rename_by, rename_by)
        data = (new_value, old_value, )
        self.cur.execute(sql, data) # Note: no % operator
        self.con.commit() # <- We MUST commit to reflect the inserted data
        return self.cur.rowcount
    
    def share_room(self, room_id, email, share_by='room_id'):
        user_id = self.get_id_by_email(email)
        if not user_id:
            self.logger.error("user {} does not exist. Could not share room {} with this user.".format(email, room_id))
            return 0
        #get room_id if not provided
        if share_by != 'room_id':
            room_id = self.get_table_field('rooms', share_by, room_id, 'id')
        if not room_id:
            self.logger.error("room {} does not exist. Could not share room with {}.".format(room_id, email))
            return 0
    
        sql = "INSERT INTO shared_accesses(room_id, user_id, created_at, updated_at) VALUES(%s, %s, %s, %s)"
        data = (room_id, user_id, self.NOW, self.NOW, )
        self.cur.execute(sql, data) # Note: no % operator
        self.con.commit() # <- We MUST commit to reflect the inserted data
        return self.cur.rowcount
    
    def show_table(self, table):
        sql = "SELECT * from {};".format(table)
        self.cur.execute(sql)
        return self.cur.fetchall()
    
    def get_id_by_email(self, email):
        self.logger.debug("fetching user_id of {}".format(email))
        sql = "SELECT id from users where email = '{}';".format(email)
        self.cur.execute(sql)
        try:
            id = self.cur.fetchall()[0][0]
        except IndexError as ERR:
            self.logger.error("Error: no user {} found. {}".format(email, ERR))
            return 0
        return int(id)
    
    def get_field_by_email(self, email, field='room_id'):
        self.logger.debug("fetching {} of {}".format(field, email))
        sql = "SELECT {} from users where email = '{}';".format(field, email)
        self.cur.execute(sql)
        try:
            id = self.cur.fetchall()[0][0]
        except IndexError as ERR:
            self.logger.error("Error: no user {} found. {}".format(email, ERR))
            return 0
        return id
    
    def get_table_field(self, table, key, value, field='room_id'):
        self.logger.debug("fetching {} of {} {}".format(field, key, value))
        sql = "SELECT {} from {} where {} = '{}';".format(field, table, key, value)
        self.cur.execute(sql)
        try:
            id = self.cur.fetchall()[0][0]
        except IndexError as ERR:
            self.logger.error("Error: no {} {} found. {}".format(key, value, ERR))
            return 0
        return id
    
    def unshare_room(self, room_id, email, share_by='room_id'):
        user_id = self.get_id_by_email(email)
        if not user_id:
            self.logger.error("user {} does not exist. Could not unshare room {} with this user.".format(email, room_id))
            return 0
    
        #get room_id if not provided
        if share_by != 'room_id':
            room_id = self.get_table_field('rooms', share_by, room_id, 'id')
        if not room_id:
            self.logger.error("room {} does not exist. Could not unshare room with {}.".format(room_id, email))
            return 0

        sql = "DELETE from shared_accesses WHERE room_id =  '{}' and user_id = '{}';".format(room_id, user_id)
        self.cur.execute(sql)
        self.con.commit() # <- We MUST commit to reflect the deleted data
        return self.cur.rowcount
    
    def delete_room(self, room_id, delete_by='uid'):
        self.logger.debug("deleting room {} {}".format(delete_by, room_id))
        sql = "SELECT id from rooms where {} = '{}';".format(delete_by, room_id)
        self.cur.execute(sql)
        try:
            id = self.cur.fetchall()[0][0]
        except IndexError as ERR:
            self.logger.error("Error: no room {} {} found. {}".format(delete_by, room_id, ERR))
            return 0
        room_id = int(id)
    
        sql = "DELETE from rooms WHERE id = '{}';".format(room_id)
        self.cur.execute(sql)
        self.con.commit() # <- We MUST commit to reflect the deleted data
        res = self.cur.rowcount
        if res > 0:
            self.logger.debug("deleted room {} {}".format(delete_by, room_id))
            # delete home room entry if available
            res3 = self.update_field('users', 'room_id', room_id, 'room_id', None)
            if res3 > 0:
                self.logger.debug("deleted homeroom")
            # delete shared rooms entries of this room
            sql = "DELETE from shared_accesses WHERE room_id = '{}';".format(room_id)
            self.cur.execute(sql)
            self.con.commit() # <- We MUST commit to reflect the deleted data
            res2 = self.cur.rowcount
            if res2 > 0:
                self.logger.debug("deleted {} shared rooms".format(res2))
        else:
            self.logger.debug("could not delete room {} {}".format(delete_by, room_id))
        return res
    
    def table_rows_as_dict(self, table, field, value, column_list):
        sql = "SELECT * from {} where {} like '{}';".format(table, field, value)
        self.cur.execute(sql)
        tableRows = {}
        for row in self.cur.fetchall():
            tableRow = []
            for i in range(len(row)):
                tableRow.append(row[i])
            room_dict = dict(zip(column_list, tableRow))
            tableRows[room_dict['id']] = room_dict
        return tableRows
    
    def table_row_as_dict(self, table, field, value, column_list):
        sql = "SELECT * from {} where {} = '{}';".format(table, field, value)
        self.cur.execute(sql)
        row = self.cur.fetchall()[0]
        tableRow = []
        for i in range(len(row)):
            tableRow.append(row[i])
        return dict(zip(column_list, tableRow))
    
    def close(self):
        self.cur.close()
        self.con.close()

    def random_secret(self, stringLength=11):
        lettersAndDigits = string.ascii_letters + string.digits
        return ''.join((random.choice(lettersAndDigits) for i in range(stringLength)))
