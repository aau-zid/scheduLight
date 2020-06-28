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
# example nginx config:
#location /scheduLight {
# rewrite ^/app/(.*) /$1 break;
# proxy_pass http://127.0.0.1:8008;
# proxy_set_header Host $host;
# proxy_set_header X-Real-IP ip_address;
# }

import sys, redis, json
from flask import Flask, request, abort
from flask_restful import Resource, Api
from gevent.pywsgi import WSGIServer
from datetime import datetime
import dataSchema
from scheduLight import scheduLight

def get_meeting_by_id(meeting_id):
    return sl.r.get('meeting:{}'.format(meeting_id))


def get_server_by_id(server_id):
    return sl.r.get('server:{}'.format(server_id))

class servers(Resource):
    def get(self):
        return { 'message': 'found servers', 'data': list(sl.r.smembers('servers'))}, 200

    def post(self):
        args = request.get_json()
        errors = sl.server_schema.validate(args)
        if errors:
            abort(400, str(errors))
        sl.r.sadd('servers', args['id'])
        sl.r.set('server:{}'.format(args['id']), json.dumps(args))
        return {"message": "server added", "data": args}, 201

class server(Resource):
    def get(self, id):
        server = get_server_by_id(id)
        if not server:
            return {"message": "server not found"}, 404 
        return { 'message': 'server found', 'data': server}, 200 

    def put(self, id):
        args = request.get_json()
        errors = sl.server_schema.validate(args)
        if errors:
            abort(400, str(errors))
        server = get_server_by_id(id)
        if server:
            sl.r.set('server:{}'.format(id), json.dumps(args))
            return { 'message': 'updated server', 'data': args}, 201
        else:
            return { 'message': 'no server with this id'}, 404

    def delete(self, id):
        sl.r.srem('servers', id)
        sl.r.delete('servers:{}:status'.format(id))
        server = get_server_by_id(id)
        if server:
            if sl.r.delete('servers:{}'.format(id)):
                return {"message": "Deleted server {}".format(server['serverName'])}, 204 
            else:
                return {"message": "could not delete server {}".format(server['serverName'])}, 404 
        else:
            return {"message": "could not find server with id {}".format(id)}, 404 

class meetings(Resource):
    def get(self):
        return { 'message': 'found meetings', 'data': list(sl.r.smembers('meetings'))}, 200

    def post(self):
        args = request.get_json()
        errors = sl.meeting_schema.validate(args)
        if errors:
            abort(400, str(errors))
        sl.r.sadd('meetings', args['id'])
        sl.r.set('meeting:{}'.format(args['id']), json.dumps(args))
        return {"message": "meeting added", "data": args}, 201

class meeting(Resource):
    def get(self, id):
        meeting = get_meeting_by_id(id)
        if not meeting:
            return {"message": "meeting not found"}, 404 
        return { 'message': 'meeting found', 'data': meeting}, 200 

    def put(self, id):
        args = request.get_json()
        errors = sl.meeting_schema.validate(args)
        if errors:
            abort(400, str(errors))
        meeting = get_meeting_by_id(id)
        if meeting:
            sl.r.set('meeting:{}'.format(id), json.dumps(args))
            return { 'message': 'updated meeting', 'data': args}, 201
        else:
            return { 'message': 'no meeting with this id'}, 404

    def delete(self, id):
        sl.r.srem('meetings', id)
        sl.r.delete('meetings:{}:status'.format(id))
        meeting = get_meeting_by_id(id)
        if meeting:
            if sl.r.delete('meetings:{}'.format(id)):
                return {"message": "Deleted meeting {}".format(meeting['meetingName'])}, 204 
            else:
                return {"message": "could not delete meeting {}".format(meeting['meetingName'])}, 404 
        else:
            return {"message": "could not find meeting with id {}".format(id)}, 404 

class meetingStatus(Resource):
    def get(self, id):
        meeting = get_meeting_by_id(id)
        if not meeting:
            return {"message": "meeting not found"}, 404 
        status = sl.r.hgetall('meeting:{}:status'.format(id))
        if not status:
            return {"message": "status not found"}, 404 
        return { 'message': 'status found', 'data': status}, 200 

    def delete(self, id):
        if sl.r.delete('meeting:{}:status'.format(id)):
            return {"message": "Deleted status {}".format(status_base)}, 204 
        else:
            return {"message": "could not delete status {}".format(id)}, 404 

class meetingProcessStatus(Resource):
    def get(self, id, status_base):
        meeting = get_meeting_by_id(id)
        if not meeting:
            return {"message": "meeting not found"}, 404 
        status = sl.r.hget('meeting:{}:status'.format(id), status_base)
        if not status:
            return {"message": "status not found"}, 404 
        return { 'message': 'status found', 'data': status}, 200 

    def put(self, id, status_base):
        args = request.get_json()
        args_json = json.dumps(args)
        if 'status_code' not in args or 'status_message' not in args:
            abort(400, 'Please provide status_code and status_message: {}'.format(args_json))
        meeting = get_meeting_by_id(id)
        if meeting:
            if sl.set_status(id, status_base.split('_'), args['status_code'], args['status_message']):
                return { 'message': 'set status', 'data': args_json}, 201
            else:
                return { 'message': 'could not set status', 'data': args_json}, 400
        else:
            return { 'message': 'no meeting with this id'}, 404

    def delete(self, id, status_base):
        if sl.r.hdel('meeting:{}:status'.format(id), status_base):
            return {"message": "Deleted status {}".format(status_base)}, 204 
        else:
            return {"message": "could not delete status {}".format(status_base)}, 404 

class commands(Resource):
    def post(self):
        args = request.get_json()
        errors = sl.command_schema.validate(args)
        if errors:
            abort(400, str(errors))
        try:
            sl.r.xadd('commandStream', { args['command']: json.dumps(args) })
            return {"message": "command queued successfully", "data": args}, 201
        except Exception as ERR:
            abort(400, str(ERR))

app = Flask(__name__)
api = Api(app, prefix="/api/v1")
api.add_resource(meetings, '/meetings')
api.add_resource(meeting, '/meetings/<string:id>')
api.add_resource(meetingStatus, '/meetings/<string:id>/status')
api.add_resource(meetingProcessStatus, '/meetings/<string:id>/status/<string:status_base>')
api.add_resource(commands, '/commands')
api.add_resource(servers, '/servers')
api.add_resource(server, '/servers/<string:id>')

if __name__ == '__main__':
    app.debug = True 
    # init sheduLight instance
    sl = scheduLight()
    http_server = WSGIServer(('', 8008), app)
    http_server.serve_forever()

# example curl calls
#curl -d '{"startDate": "2020-06-24 11:00", "id": "ms_tsy_at2", "meetingName": "test Meeting via Api", "owner": {"email": "ms@tsy.at", "fullName": "Martin T"}}' -H 'Content-Type: application/json' -X POST http://localhost:8008/api/v1/meetings
#curl -X GET http://localhost:8008/api/v1/meetings
# curl -d '{"command": "rename_room", "server": "server_to_use", "data": {"roomUID_to_rename": { "roomUID": "new_roomUID"}}}' -H 'Content-Type: application/json' -X POST http://localhost:8008/api/v1/commands
