#!/bin/bash
date >> ./saruman.log
echo "starting Saruman.." >> ./saruman.log
until python3 -u ./main.py >> ./saruman.log 2>> ./saruman.log; do
    date >> ./saruman.log
    echo "Saruman crashed with exit code $?. Respawning.." >> ./saruman.log
    sleep 10
    date >> ./saruman.log
    echo "starting Saruman.." >> ./saruman.log
done
