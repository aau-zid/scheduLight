# scheduLight
A tool to manually or automatically manage rooms and meetings in BigBlueButton and Greenlight via rest api, yaml configuration files or commandline.
You can manage multiple servers, users, rooms, sharing of rooms and much more.
Meetings can automatically be created, started and even liveStreamed (using BigBlueButton-liveStreaming), emedeately or based on a startDate.
Owners and moderators can be informed via mails. Invitations can be send to attendees.
...

The application mainly features two modes:

* oneShotCommands (from api, commandLine or a yaml config file)
* daemon mode (running in the background and whatching for changes and events to execute)

## installation

to install...
*  please clone the repository to /user/local/bin:
        git clone https://github.com/aau-zid/scheduLight.git /usr/local/bin/scheduLight

* install the python packages required... (you can use the shell script for ubuntu if you want)
        /usr/local/bin/scheduLight/python_packages_setup.sh

        ```
        apt -y install python3-pip
        apt -y install python3-psycopg2
        pip3 install -r /usr/local/bin/scheduLight/python_packages.txt
        ```

* install the systemd startup scripts...
        /usr/local/bin/scheduLight/systemd/install.sh

* configure the greenlight database 
        set the database credentials in slCli.py, slCommandProcessor.py and slMeetingProcessor.py

* start the processors...
        systemctl start scheduLight

* to stopp...
        systemctl stop scheduLight.target

### note on redis memory usage
you may have a look at Redis guidances on why vm.overcommit_memory should be set to 1 for it.
https://redis.io/topics/faq#background-saving-fails-with-a-fork-error-under-linux-even-if-i-have-a-lot-of-free-ram

## components
the application consists of the following components:

* slApi.py - a rest api listening on port 8008 for commands to be executed
* slCli.py - tool to execute commands via the cli
* slCommandProcessor.py - a daemon waiting for commands send via the api or the config file
* slMailProcessor.py - a daemon sending mails that are submitted to the queue
* slMeetingProcessor.py - a daemon waiting for meetings provided via api or config file. For more details see below
* slReadConfig.py - tool to read the config from a yaml file for processing or import data from a csv file to the config
* docker-compose.yml - config file for the redis db

* config.yml - config file to process commands or meetings
* dataSchema.py - the schema of the commands and meetings
* example.csv - example csv file for the import
* exampleConfig.yml - some examples for the config file
* greenLight.py - class with functions to interact with greenlight
* scheduLight.py - class with functions
* systemd/ - folder with systemd files
* templates/ - folder with mail templates

## general functions

### commandline (cli) functions
You can execute cli commands via the slCli.py file.

#### show running meetings on a server

-m --show_meetings
search for running meetings on a server.

-s --server
the id of the server to search on. This already has to be configured via config file or api.
Default is "bbb"

#### show or send room links

-l, --room_links 
this command searches for rooms in greenlight and shows the owner, title, link to the room and a moderator link to access the room directly without a greenlight account required.
default is to search for a name, but you can choose any column of the rooms database by specifying the following argument:

-b, --room_by - a column field of the rooms table to search in
you can send the output via email to any address by providing:

-e, --email - emailaddress to send the report to.

### commands from api or yaml file
the following commands can be triggered via the api or be configured in the yaml file for processing.

#### yaml file structure
In the yaml file use the structure below for the various commands.

```
commands:
  rename_room_cmd_id:
    command: rename_room
    server: server_to_use
    data:
      old_room_uid:
        roomUID: new_room_uid

  share_or_unshare__room_cmd_id:
    command: share_room|unshare_room
    server: server_to_use
    data:
      room_UID:
        email_to_share_to1:
        email_to_share_to2: Name

  delete_room_cmd_id:
    command: delete_room
    server: server_to_use
    data:
      room_UID:

  create_room_cmd_id:
    command: create_room
    server: server_to_use
    data:
      room name:
        email: owner email
        room_UID: UID of the room
        accessCode: code of the room

  delete_user_cmd_id:
    command: delete_user
    server: server_to_use
    data:
      email:


  create_user_cmd_id:
    command: create_user
    server: server_to_use
    data:
      email:
        fullName: name of the user
        pwd: password (not implimented yet)
        role: role of the user (default = user)
        provider: provider of the user (default = ldap)
```

### meetings from yaml file or api
if you configure meetings, the application will create users and rooms required in greenlight, start the BigBlueButton meeting emedeately or based on a startDate and optional send mails to the owner of the meeting, invitations, moderator links or notifications to users which got the room shared.
there are many automatic tasks, that can be included in the workflow. The example yaml file shows how to configure all this.

#### disable a meeting from being processed
you can set the status code via the api or redis to 900 to have the meeting being ignored.

### servers
to use any of the functions you will have to configure at least one BigbLuebutton server that can be used for the tasks. This can be done via the config file or the api.

### mailProcessor
The mailProcessor listens to a redis stream for new mails to be send.
mails by default will be send on behalf of the owner of a meeting. This can be overridden on server or even meeting level.
For commands you have to provide the sender in the command or on server level to enable mail functionality.

to prevent sending of unwanted mails, mail processing is off by default.
You can activate sending mails on server or meeting basis, or only for share notification mails.
set send_emails variable to true on the desired level - see the example.
For testing purposes you always can supply the -n --no_mail  argument on the commandline for the mailProcessor to prevent sending of any mail.
If mail transport is turned off, you will see the mails in the logs.
The -d --debug_emails flag does enable verbose mode and output the whole mail.

### api command structure and examples
you can trigger all commands or the processing of meetings via the api. For the available functions see the commands and meetings notes. You also can setup servers or manage the status of meetings and their workflow.

to configure servers, meetings and commands via the api you have to call the rest api as follows. the structure is the same as in the config file for simplicity:

```
curl -d '{ "command": "rename_room", "server": "server_to_use", "data": { "old_room_uid": { "roomUID": "new_room_uid" } } }' -H 'Content-Type: application/json' -X POST http://localhost:8008/api/v1/commands
curl -d '{"startDate": "2020-06-24 11:00", "id": "id_to_use", "meetingName": "test Meeting via Api", "owner": {"email": "email_of_owner", "fullName": "your name"}}' -H 'Content-Type: application/json' -X POST http://localhost:8008/api/v1/meetings
curl -X GET http://localhost:8008/api/v1/meetings
curl -X GET http://localhost:8008/api/v1/meetings/meetingID
curl -d '{"command": "rename_room", "server": "server_to_use", "data": {"roomUID_to_rename": { "roomUID": "new_roomUID"}}}' -H 'Content-Type: application/json' -X POST http://localhost:8008/api/v1/commands
```

## todo and known limitations
### orm based database management
the interaction with the greenLight sql database should be changed to Object Relational Mapping:
https://www.sqlalchemy.org/
https://marshmallow.readthedocs.io/en/3.0/examples.html

### room settings
should all be added as variables in the create_room function, as create params in create_meeting already have been.

### password of new users
the user password has to be blowfish encrypted to be compatible to greenlight. What is the salt greenlight uses?
import bcrypt
password = "123456"
pw = bcrypt.hashpw(password.encode('utf-8'), salt.encode('utf-8'))

### api calls for mail queue
mail queue management should be added to the api.
Allowing:

* list new mails
* list old mails
* delete mail from a queue
* delete all mails from a queue

### delete recordings when a room is deleted
fetch all recordings related to a greenLight room and delete them when the room is deleted.

### application wide config file
provide an application wide config file instead of (or additionally to) the args in the cli, command and meeting scripts.
extend the systemd files to use values from the config file on startup.

### extend documentation
