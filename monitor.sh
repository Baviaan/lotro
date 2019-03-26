#!/bin/bash
# This assumes all files for Saruman are stored in ~/lotro/
cd ~/lotro/
date >> ./saruman.log
echo "starting Saruman.." >> ./saruman.log
until python3 -u ./lotro.py >> ./saruman.log 2>> ./saruman.log; do
    date >> ./sarumanerror.log
    echo "Saruman crashed with exit code $?. Respawning.." >> ./sarumanerror.log
    sleep 5
    date >> ./saruman.log
    echo "starting Saruman.." >> ./saruman.log
done
