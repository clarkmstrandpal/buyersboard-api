
import json, boto3
_ssm = boto3.client("ssm")
def get_param(name):
    return _ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
def get_json_param(name):
    return json.loads(get_param(name))
