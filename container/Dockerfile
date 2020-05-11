FROM ubuntu:18.04
RUN apt-get update && apt-get -y install python3 python3-pip
RUN python3 -m pip install boto3
COPY task.py /
CMD ["python3", "./task.py"]
