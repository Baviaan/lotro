FROM python:3.10.4

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -U -r requirements.txt

COPY /source/ .

CMD [ "python", "./main.py" ]
