#!/bin/bash
set -euf -o pipefail

# Ensure .env files are present
env_file_errors=()
env_files=("backend/.env" "frontend/apps/web/.env")
for file in "${env_files[@]}"; do
    if [ ! -f "/workspace/$file" ]; then
        template_file="/workspace/${file}.template"
        example_file="/workspace/${file}.example"
        if [ -f "$template_file" ]; then
            cp "$template_file" "/workspace/$file"
            echo "Created $file from template file"
        elif [ -f "$example_file" ]; then
            cp "$example_file" "/workspace/$file"
            echo "Created $file from example file"
        else
            env_file_errors+=("Error: .env file not found in $file folder and no template/example file exists.")
        fi
    fi
done

# Define color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

echo -e "${GREEN}Environment variables ------------------------------${NC}"
if [ ${#env_file_errors[@]} -ne 0 ]; then
    for message in "${env_file_errors[@]}"; do
        echo -e "${YELLOW}$message${NC}"
    done
else
    echo -e "${GREEN}${BOLD}All .env files found or created from templates!${NC} Please check the files for any missing variables."
fi

# A development deployment gets its own random key so credential features in
# Admin > Models and Admin > Storage work without manual setup. Never fires
# once a key is present.
if [ -f "/workspace/backend/.env" ] && ! grep -Eq '^[[:space:]]*ENCRYPTION_KEY=[^[:space:]]+' "/workspace/backend/.env"; then
    VENV_PYTHON="/workspace/backend/.venv/bin/python"
    GENERATED_KEY=""
    if [ -x "$VENV_PYTHON" ]; then
        GENERATED_KEY="$("$VENV_PYTHON" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' 2>/dev/null || true)"
    fi
    if [ -n "$GENERATED_KEY" ]; then
        if grep -Eq '^[[:space:]]*ENCRYPTION_KEY=' "/workspace/backend/.env"; then
            sed -i "s|^[[:space:]]*ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$GENERATED_KEY|" "/workspace/backend/.env"
        else
            printf '\nENCRYPTION_KEY=%s\n' "$GENERATED_KEY" >> "/workspace/backend/.env"
        fi
        echo -e "${GREEN}Generated a development ENCRYPTION_KEY in backend/.env.${NC}"
    else
        echo -e "${YELLOW}${BOLD}ENCRYPTION_KEY is empty.${NC} Saving credentials in Admin > Models or Admin > Storage will fail until it is configured."
        echo "Generate one with: cd backend && uv run python -m eneo.cli.generate_encryption_key"
        echo "Add the generated value to backend/.env, then restart the backend."
    fi
fi

# The object-content profile is optional; only hint when its SeaweedFS
# container is actually on the network.
if getent hosts object-content >/dev/null 2>&1; then
    echo ""
    echo -e "${GREEN}Local object storage (SeaweedFS) is running ---------${NC}"
    echo "Connect it in Admin > Storage:"
    echo "  Endpoint:   http://object-content:8333"
    echo "  Region:     local"
    echo "  Bucket:     eneo-object-content-dev"
    echo "  Access key: eneo-dev-object-content"
    echo "  Secret key: local-development-only-secret"
fi

echo ""
echo -e "${BLUE}${BOLD}To run the project, use the following commands${NC}"
echo ""
echo -e "${GREEN}Backend --------------------------------------------${NC}"
echo "cd backend"
echo -e "${YELLOW}# If this is your first run, execute migrations:${NC}"
echo "uv run python init_db.py"
echo ""
echo -e "${GREEN}# Start the backend:${NC}"
echo "uv run start"
echo ""
echo -e "${GREEN}Frontend --------------------------------------------${NC}"
echo "cd frontend"
echo "bun run dev"
echo ""
echo -e "${GREEN}Optional: local S3 object storage -------------------${NC}"
echo "docker compose -p eneo_devcontainer -f .devcontainer/docker-compose.yml --profile object-content up -d object-content"
echo ""
echo -e "${BLUE}Open your browser and go to ${BOLD}http://localhost:3000${NC}"
echo -e "${BLUE}Login with${NC}"
echo -e "${BOLD}email: user@example.com"
echo -e "password: Password1!${NC}"
echo ""
echo -e "${GREEN}${BOLD}You can now start developing!${NC}"
echo ""
