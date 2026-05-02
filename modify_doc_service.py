import re

file_path = 'backend/app/services/document_service.py'

with open(file_path, 'r') as f:
    content = f.read()

# 1. Add import
if 'from app.services import settings_service' not in content:
    content = re.sub(r'from app.config import settings\n', 'from app.config import settings\nfrom app.services import settings_service\n', content)

# 2. Update settings.VISION_ENABLED
content = re.sub(r'settings\.VISION_ENABLED', 'settings_service.get("VISION_ENABLED")', content)

with open(file_path, 'w') as f:
    f.write(content)

print("document_service.py updated.")
