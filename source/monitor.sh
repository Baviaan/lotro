#!/bin/bash
date >> ./saruman.log
echo "starting Saruman.." >> ./saruman.log
let n=20
until python3 -u ./main.py >> ./saruman.log 2>> ./saruman.log; do
    date >> ./saruman.log
    echo "Saruman crashed with exit code $?. Respawning.." >> ./saruman.log
    sleep $n
    date >> ./saruman.log
    echo "starting Saruman.." >> ./saruman.log
    n=$((n*12/10))
done
