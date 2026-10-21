"""Deployment response identity and matching token-count inputs."""
from copy import deepcopy

ANSWER_CHECKLIST='''作答检查（对所有检索方法相同）：先按用户问题中的每个问句和已给条件安排查询，搜索具体模型名、参数名及必要英文名称。首次命中不表示资料齐全；需要比较、默认值或适用条件时，补读相应说明与配置。最终回答按用户所问逐项说明，给出原文支持的定义、数值、判断及理由；区别默认与实例。不要添加无法核验的技术延伸或运行保证。最后检查是否遗漏问题中的子问。工具动作的action只能是tool，例如 {"action":"tool","name":"search","arguments":{"query":"具体标识与所需含义"}}；不要写action=search。最终动作严格使用final、answer、references三个字段。'''


def prepared_messages(messages,addendum):
    actual=deepcopy(messages)
    if addendum:
        actual[0]['content']+='\n'+addendum
    return actual


class DeploymentResponse:
    """Expose an explicit interface alias; preserve actual model in raw receipt."""
    def __init__(self,client,logical_model,addendum=''):
        self.client,self.logical_model=client,logical_model
        self.addendum=addendum

    def __call__(self,body,turn):
        actual={**body,'messages':prepared_messages(body['messages'],self.addendum)} if self.addendum else body
        record=self.client(actual,turn)
        if record['status']!='response':return record
        raw=record['raw_response']
        if raw.get('model')!=self.client.deployment.model:
            raise ValueError('Actual deployed model differs')
        return {**record,'response':{**raw,'model':self.logical_model},
            'response_interface_alias':dict(actual_model=raw['model'],logical_model=self.logical_model,
                policy='Explicit deployment alias only; original provider receipt unchanged.')}


def token_counter(raw,workload,addendum=''):
    def counter(messages):
        actual=prepared_messages(messages,addendum)
        if workload=='small':
            for message in reversed(actual):
                if message['role']=='user':
                    if not message['content'].rstrip().endswith('/no_think'):
                        message['content']+='\n/no_think'
                    break
        return raw(actual)
    return counter
