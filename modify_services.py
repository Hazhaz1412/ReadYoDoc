import re

files_to_modify = [
    'backend/app/services/embedding_service.py',
    'backend/app/services/vision_service.py',
    'backend/app/services/chunking_service.py'
]

for file_path in files_to_modify:
    with open(file_path, 'r') as f:
        content = f.read()
    
    # 1. Add import
    if 'from app.services import settings_service' not in content:
        content = re.sub(r'from app.config import settings\n', 'from app.config import settings\nfrom app.services import settings_service\n', content)
    
    # 2. Update embedding_service
    if 'embedding_service.py' in file_path:
        content = re.sub(r'"model": settings\.EMBEDDING_MODEL', '"model": settings_service.get("EMBEDDING_MODEL")', content)
        content = re.sub(r'settings\.EMBEDDING_MODEL in name', 'settings_service.get("EMBEDDING_MODEL") in name', content)

    # 3. Update vision_service
    if 'vision_service.py' in file_path:
        content = re.sub(r'if not settings\.VISION_ENABLED:', 'if not settings_service.get("VISION_ENABLED"):', content)
        content = re.sub(r'"model": settings\.VISION_MODEL', '"model": settings_service.get("VISION_MODEL")', content)
        content = re.sub(r'settings\.VISION_MODEL in name', 'settings_service.get("VISION_MODEL") in name', content)

    # 4. Update chunking_service
    if 'chunking_service.py' in file_path:
        # we need to replace settings.CHUNK_SIZE and settings.CHUNK_OVERLAP
        # Let's see if we can do a global replace
        content = re.sub(r'settings\.CHUNK_SIZE', 'settings_service.get("CHUNK_SIZE")', content)
        content = re.sub(r'settings\.CHUNK_OVERLAP', 'settings_service.get("CHUNK_OVERLAP")', content)

    with open(file_path, 'w') as f:
        f.write(content)

print("Services updated.")
