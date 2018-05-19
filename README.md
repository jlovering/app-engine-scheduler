## Google Cloud Platform - Schedule Start

### In a few words
This is a simple application engine that will start a group of instances and can be triggered by a cron job. Also shows basic status about if an instance is running.

### How to deploy
- Make sure you have gcloud tool installed on your computer https://cloud.google.com/sdk/
- Make sure you have access to the Google Cloud Platform project where you want to deploy this tool
- Place yourself in this code repository and run the following below:
```
virtualenv env
source env/bin/activate
pip install -t lib -r requirements.txt
deactivate
gcloud app deploy app.yaml --project <my project id>
gcloud app deploy cron.yaml --project <my project id>
```
- Add following permission at organization level to the service account associated with Google App Engine (can be found under IAM > Service accounts > App Engine app default service account):
```
compute.instances.list
compute.instances.get
compute.instances.start
compute.instances.stop
```

### Author

Jon Lovering - jon.lovering@gmail.com

Heavily based GCE scheduler by
Paul Chapotet — paul@chapotet.com
