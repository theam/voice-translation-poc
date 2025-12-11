# ACS Lambda Code

Azure Function for Azure Communication Services event handling.

## Deployment

To deploy this function to Azure:

1. Install dependencies locally in this folder:
   ```bash
   cd acs_lambda_code
   pip install -r requirements.txt --target .
   ```

2. Compress all contents into a ZIP file:
   ```bash
   zip -r function.zip .
   ```

3. Upload the ZIP file to Azure Functions via Azure Portal or CLI:
   ```bash
   az functionapp deployment source config-zip \
     --resource-group <resource-group> \
     --name <function-app-name> \
     --src function.zip
   ```

**Important:** The dependencies must be installed directly in the `acs_lambda_code` folder (not in a virtual environment) so they are included in the deployment package.
