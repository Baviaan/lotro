FROM python:3.9.13

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -U -r requirements.txt

COPY /source/ .

CMD [ "python", "./main.py" ]
