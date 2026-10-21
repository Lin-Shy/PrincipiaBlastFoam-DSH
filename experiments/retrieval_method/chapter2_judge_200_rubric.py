"""Question-bound original audit; source-free coverage remains separate."""
from chapter2_source_free_answer_scoring import source_free_requests
from chapter2_reasoning_answer_scoring import parse_reasoning_judgments
from chapter2_partial_answer_scoring import parse_partial_judgments

CONDITION_RULE = '''
The natural question's stated constraints are binding premises. First identify them before evaluating the candidate. In condition.reason, quote the relevant constraint verbatim from question and apply it to the candidate's actual conclusion. Do not replace the stated condition by a looser hypothetical one. Respect equality/inequality, zero/nonzero, disabled/enabled, only/except, selected model and unchanged-file constraints. A statement that something COULD happen does not support a candidate claiming it MUST happen. A true general definition cannot make a conclusion under incompatible given conditions correct. Evaluate exact numerical/algebraic implications when the supplied definitions suffice, without requiring a sentence in the manual to repeat the entire question.
'''

COVERAGE_RULE = '''
If the candidate explicitly contradicts any necessary component of the hypothesis, use wrong even when another component overlaps correctly. Use partial for incomplete compatible content, not for an affirmative incompatible conclusion. A requested explanation or boundary cannot be filled with source knowledge that is absent from the candidate premise.
'''


def requests(payload):
    rows = source_free_requests(payload)
    for row in rows:
        row['body']['messages'][0]['content'] += CONDITION_RULE if row['stage']=='independent_original_truth_audit' else COVERAGE_RULE
    return rows


def parse(records, payload):
    reqs = requests(payload)
    def strict(responses, packet):
        return parse_reasoning_judgments(responses, packet, requests=reqs)
    return parse_partial_judgments(records, payload, requests=reqs, strict_parser=strict,
        rubric_version='source_free_question_bound_200_v2')
