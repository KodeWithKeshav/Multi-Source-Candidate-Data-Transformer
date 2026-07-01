import re

def _resolve_path(obj, path):
    parts = path.split(".")
    for part in parts:
        if obj is None:
            return None
        
        match = re.match(r"([^\[]+)\[(\d+)\]", part)
        if match:
            attr_name = match.group(1)
            idx = int(match.group(2))
            
            if hasattr(obj, attr_name):
                obj = getattr(obj, attr_name)
            elif isinstance(obj, dict):
                obj = obj.get(attr_name)
            else:
                return None
                
            if isinstance(obj, list) and idx < len(obj):
                obj = obj[idx]
            else:
                return None
        else:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            elif isinstance(obj, dict):
                obj = obj.get(part)
            else:
                return None
    return obj

class Dummy:
    def __init__(self):
        self.experience = [{"company": "Microsoft"}]

d = Dummy()
print(_resolve_path(d, "experience[0].company"))

