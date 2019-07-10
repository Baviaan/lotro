#!/bin/bash
# This assumes all files for Saruman are stored in ~/lotro/source
cd ~/lotro/source
date >> ./saruman.log
echo "starting Saruman.." >> ./saruman.log
until python3 -u ./main.py >> ./saruman.log 2>> ./saruman.log; do
    date >> ./sarumanerror.log
    echo "Saruman crashed with exit code $?. Respawning.." >> ./sarumanerror.log
    sleep 10
    date >> ./saruman.log
    echo "starting Saruman.." >> ./saruman.log
done
