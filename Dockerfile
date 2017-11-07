FROM python:3

WORKDIR /code

COPY requirements.txt /code
RUN pip3 install --no-cache-dir -r requirements.txt

# RUN python azure-event-hubs-python-master/setup.py
COPY readIotHubAmqpClient.py /code

CMD [ "python3", "./readIotHubAmqpClient.py" ]