#!/bin/bash
set -e
targetDir=/lib/systemd/system
linkDir=/etc/systemd/system
echo "uninstalling systemd files..."
if [[ -f $targetDir/scheduLight-api.service ]]; then
    systemctl disable scheduLight-api.service
fi
for file in /usr/local/bin/scheduLight/systemd/scheduLight*
do
    if [[ -f $file ]]; then
        rm -f $targetDir/${file##*/}
        rm -f $linkDir/${file##*/}
    fi
done
systemctl daemon-reload
