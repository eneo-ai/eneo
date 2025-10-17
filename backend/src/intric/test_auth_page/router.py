import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

router = APIRouter(prefix="/test-auth", tags=["Test Auth Page"])
security = HTTPBasic()

# Simple credentials for testing
TEST_USERNAME = "testuser"
TEST_PASSWORD = "testpass123"


def verify_credentials(credentials: Annotated[HTTPBasicCredentials, Depends(security)]):
    """Verify HTTP basic auth credentials."""
    current_username_bytes = credentials.username.encode("utf8")
    correct_username_bytes = TEST_USERNAME.encode("utf8")
    is_correct_username = secrets.compare_digest(
        current_username_bytes, correct_username_bytes
    )
    current_password_bytes = credentials.password.encode("utf8")
    correct_password_bytes = TEST_PASSWORD.encode("utf8")
    is_correct_password = secrets.compare_digest(
        current_password_bytes, correct_password_bytes
    )
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@router.get("/", response_class=HTMLResponse)
async def test_page(username: Annotated[str, Depends(verify_credentials)]):
    """Simple test page with HTTP basic auth."""

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Test Auth Page</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
                background-color: #f5f5f5;
            }}
            .container {{
                background-color: white;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            h1 {{
                color: #333;
            }}
            .info {{
                background-color: #e3f2fd;
                padding: 15px;
                border-left: 4px solid #2196f3;
                margin: 20px 0;
            }}
            .download-btn {{
                display: inline-block;
                background-color: #4CAF50;
                color: white;
                padding: 12px 24px;
                text-decoration: none;
                border-radius: 4px;
                margin: 10px 0;
                transition: background-color 0.3s;
            }}
            .download-btn:hover {{
                background-color: #45a049;
            }}
            .credentials {{
                background-color: #fff3cd;
                padding: 15px;
                border-left: 4px solid #ffc107;
                margin: 20px 0;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>✅ Authentication Successful!</h1>

            <div class="info">
                <strong>Welcome, {username}!</strong>
                <p>You have successfully authenticated using HTTP Basic Auth.</p>
            </div>

            <div class="credentials">
                <strong>Test Credentials:</strong>
                <ul>
                    <li>Username: <code>testuser</code></li>
                    <li>Password: <code>testpass123</code></li>
                </ul>
            </div>

            <h2>Download Test File</h2>
            <p>Click the button below to download a sample PDF file:</p>
            <a href="sample-file.pdf" class="download-btn">📥 Download Sample PDF</a>

            <h2>About This Page</h2>
            <p>This is a simple test page demonstrating HTTP Basic Authentication and file downloads.</p>
            <ul>
                <li>Secured with HTTP Basic Auth</li>
                <li>File download functionality</li>
                <li>Useful for testing authentication flows</li>
            </ul>
        </div>
    </body>
    </html>
    """
    return html_content


@router.get("/sample-file.pdf")
async def download_file(username: Annotated[str, Depends(verify_credentials)]):
    """Download a sample file (requires authentication)."""
    from pathlib import Path

    # Path to the sample file in the test_auth_page directory
    file_path = Path(__file__).parent / "sample-file.pdf"

    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sample file not found"
        )

    return FileResponse(
        path=str(file_path),
        filename="sample-file.pdf",
        media_type="application/pdf"
    )


@router.get("/public", response_class=HTMLResponse)
async def public_test_page():
    """Simple test page WITHOUT HTTP basic auth."""
    from intric.main.config import get_settings

    api_prefix = get_settings().api_prefix
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Public Test Page</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
                background-color: #f5f5f5;
            }}
            .container {{
                background-color: white;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            h1 {{
                color: #333;
            }}
            .info {{
                background-color: #e3f2fd;
                padding: 15px;
                border-left: 4px solid #2196f3;
                margin: 20px 0;
            }}
            .download-btn {{
                display: inline-block;
                background-color: #4CAF50;
                color: white;
                padding: 12px 24px;
                text-decoration: none;
                border-radius: 4px;
                margin: 10px 0;
                transition: background-color 0.3s;
            }}
            .download-btn:hover {{
                background-color: #45a049;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Public Test Page (No Auth)</h1>

            <div class="info">
                <p>This is a public test page without authentication.</p>
                <p>Use this to test if the crawler can download files when no auth is required.</p>
            </div>

            <h2>Download Test File</h2>
            <p>Click the button below to download a sample PDF file:</p>
            <a href="{api_prefix}/test-auth/public/sample.pdf" class="download-btn">📥 Download Sample PDF</a>

            <h2>About This Page</h2>
            <p>This page tests file downloads WITHOUT HTTP Basic Authentication.</p>
            <ul>
                <li>No authentication required</li>
                <li>Public file download</li>
                <li>Useful for isolating auth issues</li>
            </ul>
        </div>
    </body>
    </html>
    """
    return html_content


@router.get("/public/sample.pdf")
async def download_public_file():
    """Download a sample file WITHOUT authentication."""
    from pathlib import Path

    # Path to the sample file in the test_auth_page directory
    file_path = Path(__file__).parent / "sample-file.pdf"

    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sample file not found"
        )

    return FileResponse(
        path=str(file_path),
        filename="sample.pdf",
        media_type="application/pdf"
    )


@router.get("/auth-file", response_class=HTMLResponse)
async def auth_file_test_page(username: Annotated[str, Depends(verify_credentials)]):
    """Test page with BOTH page AND file requiring HTTP basic auth."""

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Auth File Test Page</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
                background-color: #f5f5f5;
            }}
            .container {{
                background-color: white;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            h1 {{
                color: #333;
            }}
            .info {{
                background-color: #e3f2fd;
                padding: 15px;
                border-left: 4px solid #2196f3;
                margin: 20px 0;
            }}
            .download-btn {{
                display: inline-block;
                background-color: #4CAF50;
                color: white;
                padding: 12px 24px;
                text-decoration: none;
                border-radius: 4px;
                margin: 10px 0;
                transition: background-color 0.3s;
            }}
            .download-btn:hover {{
                background-color: #45a049;
            }}
            .credentials {{
                background-color: #fff3cd;
                padding: 15px;
                border-left: 4px solid #ffc107;
                margin: 20px 0;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔒 Auth File Download Test</h1>

            <div class="info">
                <strong>Welcome, {username}!</strong>
                <p>Both this page AND the file download below require HTTP Basic Authentication.</p>
            </div>

            <div class="credentials">
                <strong>Test Credentials:</strong>
                <ul>
                    <li>Username: <code>testuser</code></li>
                    <li>Password: <code>testpass123</code></li>
                </ul>
            </div>

            <h2>Protected File Download</h2>
            <p>This PDF file is protected with HTTP Basic Auth:</p>
            <a href="auth-file/auth-file-protected.pdf" class="download-btn">🔐 Download Protected PDF</a>

            <h2>Test Scenario</h2>
            <p>This page demonstrates:</p>
            <ul>
                <li>✅ Page requires HTTP Basic Auth</li>
                <li>✅ File download ALSO requires HTTP Basic Auth</li>
                <li>✅ Crawler must authenticate for both the page and the file</li>
            </ul>
        </div>
    </body>
    </html>
    """
    return html_content


@router.get("/auth-file/auth-file-protected.pdf")
async def download_protected_file(username: Annotated[str, Depends(verify_credentials)]):
    """Download a file that ALSO requires authentication (testing auth on file downloads)."""
    from pathlib import Path

    # Path to the sample file in the test_auth_page directory
    file_path = Path(__file__).parent / "sample-file.pdf"

    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sample file not found"
        )

    return FileResponse(
        path=str(file_path),
        filename="auth-file-protected.pdf",
        media_type="application/pdf"
    )
