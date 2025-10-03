#!/bin/bash
# Copyright (c) 2024 Sundsvalls Kommun
#
# Licensed under the MIT License.

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

echo ""
echo -e "${BLUE}${BOLD}To run the project, use the following commands${NC}"
echo ""
echo -e "${GREEN}Backend --------------------------------------------${NC}"
echo "cd backend"
echo -e "${YELLOW}# If this is your first run, execute migrations:${NC}"
echo "poetry run python init_db.py"
echo ""
echo -e "${GREEN}# Start the backend:${NC}"
echo "poetry run start"
echo ""
echo -e "${GREEN}Frontend --------------------------------------------${NC}"
echo "cd frontend"
echo "pnpm run dev"
echo ""
echo -e "${BLUE}Open your browser and go to ${BOLD}http://localhost:3000${NC}"
echo -e "${BLUE}Login with${NC}"
echo -e "${BOLD}email: user@example.com"
echo -e "password: Password1!${NC}"
echo ""
echo -e "${GREEN}${BOLD}You can now start developing!${NC}"
echo ""