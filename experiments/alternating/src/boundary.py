"""Offline handoff contract. No SDK imports, no model calls, no fabricated observations."""
import copy,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def canonical(x):return json.dumps(x,ensure_ascii=False,separators=(',',':'))
def public_text(s):return {k:s[k] for k in ('submission_id','author_id','text')}
def evaluation_payload(submission):
 # Used identically by persistent single, isolated B, and isolated baseline.
 return {'current_submission':public_text(submission)}
def route_input(request_id,submission):return {'event':'user_evaluation_request','request_id':request_id,'current_submission':public_text(submission)}
def delegate(reply,request_id,submission):
 # Do not accept text/analysis/prompt hints written by the coordinator.
 if reply!={'action':'delegate','request_id':request_id}:raise ValueError('invalid_route_or_extra_information')
 return copy.deepcopy(evaluation_payload(submission))
def result_input(request_id,evaluation_id,actual_evaluation):
 return {'event':'evaluation_completed','request_id':request_id,'evaluation_id':evaluation_id,'evaluation':copy.deepcopy(actual_evaluation)}
def deliver(reply,request_id,evaluation_id,actual_evaluation):
 if reply!={'action':'deliver','request_id':request_id,'evaluation_id':evaluation_id}:raise ValueError('invalid_delivery_or_rewritten_result')
 # The host renders the original evaluator result as the user-visible answer.
 return copy.deepcopy(actual_evaluation)
def fingerprint(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
