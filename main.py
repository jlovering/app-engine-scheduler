import jinja2
import webapp2
import datetime

from googleapiclient import discovery
from oauth2client.client import GoogleCredentials

jinja_environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader('templates'))

compute = discovery.build('compute','v1',
    credentials=GoogleCredentials.get_application_default())

projectID = 'wrf-blipmaps'
bayarea_4k_instances = [
    {
        'name':'rasp-blipmap-bayarea-4k-0',
        'zone':'us-west1-a'
    },
    {
        'name':'rasp-blipmap-bayarea-4k-1',
        'zone':'us-west1-a'
    },
    {
        'name':'rasp-blipmap-bayarea-4k-2',
        'zone':'us-west1-a'
    }
]

def get_time():
    return datetime.datetime.now().strftime('[%Y-%m-%d %H:%M:%S] ')

def start_instance(project, zone, instance):
    """starts instance"""
    request = compute.instances().start(
        project=project,
        zone=zone,
        instance=instance)
    response = request.execute()
    return response

def get_status(project, zone, instance):
    request = compute.instances().get(
        project=project,
        zone=zone,
        instance=instance)
    response = request.execute()
    return response['status']

class BayArea4kStartPage(webapp2.RequestHandler):
    def get(self):
        for instance in bayarea_4k_instances:
            start_instance(projectID, instance['zone'], instance['name'])
            self.response.write(get_time() +
                "Starting instance: " + instance['name'] + "\r\n")

class StatusPage(webapp2.RequestHandler):
    def get(self):
        status_items = [];
        for instance in bayarea_4k_instances:
                status_items.append({
                    'instance_name': instance['name'],
                    'instance_status': get_status(projectID, instance['zone'], instance['name'])
                    })

        data = {}
        data['title'] = "Instance Status"
        data['date'] = datetime.datetime.now()
        data['status_items'] = status_items

        template = jinja_environment.get_template('status.html')
        self.response.out.write(template.render(data))

app = webapp2.WSGIApplication([
    ('/BayArea4kStart', BayArea4kStartPage),
    ('/Status', StatusPage),
], debug=True)

