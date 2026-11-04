"""Read-only checks of actual provider frames and progressive skill reads."""
import re
from pathlib import Path

SKILLS = {'cap_brave': ('brave-search', 'bx-search'), 'cap_browser': ('playwright-cli', 'playwright-cli'),
          'cap_db': ('psql', 'psql'), 'cap_gh': ('gh', 'gh')}
PROGRAMS = {'cap_brave': 'bx', 'cap_browser': 'playwright-cli', 'cap_db': 'psql', 'cap_gh': 'gh-github'}
for task in ('gaia_1', 'gaia_2'):
    SKILLS[task], PROGRAMS[task] = SKILLS['cap_brave'], PROGRAMS['cap_brave']
for task in ('employee_demographics_report', 'employee_hierarchy_management'):
    SKILLS[task], PROGRAMS[task] = SKILLS['cap_db'], PROGRAMS['cap_db']
for task in ('products_sales_analysis','customer_segmentation_setup'):
    SKILLS[task],PROGRAMS[task]=SKILLS['cap_browser'],PROGRAMS['cap_browser']
for task in ('find_salient_file','release_management_workflow'):
    SKILLS[task], PROGRAMS[task] = SKILLS['cap_gh'], PROGRAMS['cap_gh']
COMPONENTS={'composite_1':('cap_brave','cap_db'),'composite_2':('cap_db','cap_gh')}


def components(task):
    return COMPONENTS.get(task,(task,) if task in SKILLS else ())


def programs_for(task):
    return [PROGRAMS[t] for t in components(task)]


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


def read_before_cli(task,messages):
    folder='/skills/'+SKILLS[task][1]+'/SKILL.md'
    read_ids=set()
    loaded=False
    for msg in messages:
        if msg.get('role')=='toolResult' and msg.get('toolCallId') in read_ids and not msg.get('isError'):
            loaded=True
        if msg.get('role')!='assistant':continue
        for block in msg.get('content',[]):
            if not isinstance(block,dict) or block.get('type')!='toolCall':continue
            args=block.get('arguments',{})
            if block['name']=='read' and folder in args.get('path',''):
                read_ids.add(block['id'])
            if block['name']=='bash':
                command=args.get('command','')
                if ('cat ' in command or 'read_text' in command) and folder in command:
                    read_ids.add(block['id'])
                if re.search(r'\b'+re.escape(PROGRAMS[task])+r'''(?=\s|['"]|$)''',command):
                    return loaded
    return None


def audit(row, first, messages, traces):
    prompt='\n'.join(strings(first))
    actual=sorted(re.findall(r'<skill>\s*<name>([^<]+)</name>',prompt))
    required=components(row['task'])
    expected=[]
    if row['mode']=='cli':
        expected=sorted({s[0] for s in SKILLS.values()} if row['catalog']=='full' else {SKILLS[t][0] for t in required})
    result={'initial_skill_names':actual,'expected_skill_names':expected,
        'skill_metadata_matches':actual==expected,
        'personal_context_absent':'ponytail' not in prompt.lower() and str(Path.home()) not in prompt,
        'observed_api_settings':{k:first[k] for k in ('model','reasoning','reasoning_effort','thinking','max_tokens','max_output_tokens','temperature','store') if k in first},
        'cli_invocations':traces}
    if row['mode']!='cli' or not required:
        result['skill_read_before_cli']=None
    else:
        checks={PROGRAMS[t]:read_before_cli(t,messages) for t in required}
        result['skill_reads_by_program']=checks
        result['skill_read_before_cli']=next(iter(checks.values())) if len(checks)==1 else all(v is True for v in checks.values())
    return result
