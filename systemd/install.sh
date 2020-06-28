#!/bin/bash
set -e
targetDir=/lib/systemd/system
linkDir=/etc/systemd/system
echo "installing systemd files..."
for file in /usr/local/bin/scheduLight/systemd/scheduLight*
do
    if [[ -f $file ]]; then
        cp $file $targetDir
    fi
done
systemctl daemon-reload
if [[ -f $targetDir/scheduLight-api.service ]]; then
    systemctl enable scheduLight-api.service
fi
