
import logging
import os
import json
import azure.functions as func

try:
    from azure.communication.callautomation import (
        CallAutomationClient,
        MediaStreamingOptions,
        StreamingTransportType,
        MediaStreamingContentType,
        MediaStreamingAudioChannelType,
        AudioFormat,
    )
    CALLAUTOMATION_AVAILABLE = True
except ModuleNotFoundError:
    logging.warning("azure.communication.callautomation NO está instalado todavía")
    CALLAUTOMATION_AVAILABLE = False

ACS_CONNECTION_STRING = os.environ.get("ACS_CONNECTION_STRING")
CALLBACK_URL = os.environ.get("CALLBACK_URL")

WEBSOCKET_URL = os.environ.get("WEBSOCKET_URL")

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Evento de ACS/Event Grid recibido")

    try:
        events = req.get_json()
    except Exception:
        body = req.get_body().decode(errors="ignore")
        logging.error(f"No se pudo parsear JSON. Body: {body}")
        return func.HttpResponse("Invalid JSON", status_code=400)

    if not isinstance(events, list):
        events = [events]

    for event in events:
        event_type = (
            event.get("eventType")
            or event.get("event_type")
            or event.get("type")
        )

        if event_type == "Microsoft.EventGrid.SubscriptionValidationEvent":
            validation_code = event["data"]["validationCode"]
            return func.HttpResponse(
                body=json.dumps({"validationResponse": validation_code}),
                mimetype="application/json",
                status_code=200,
            )

        if event_type == "Microsoft.Communication.IncomingCall":
            _handle_incoming_call(event)

    return func.HttpResponse("OK", status_code=200)

def _handle_incoming_call(event: dict) -> None:
    if not CALLAUTOMATION_AVAILABLE:
        logging.error("CallAutomation no disponible (paquete no instalado)")
        return

    if not ACS_CONNECTION_STRING or not CALLBACK_URL:
        logging.error("Variables ACS_CONNECTION_STRING o CALLBACK_URL faltan")
        return

    data = event.get("data", {})
    incoming_call_context = data.get("incomingCallContext")
    if not incoming_call_context:
        logging.error("incomingCallContext no presente")
        return

    client = CallAutomationClient.from_connection_string(ACS_CONNECTION_STRING)

    media_streaming_options = MediaStreamingOptions(
        transport_url=WEBSOCKET_URL,
        transport_type=StreamingTransportType.WEBSOCKET,
        content_type=MediaStreamingContentType.AUDIO,
        audio_channel_type=MediaStreamingAudioChannelType.UNMIXED,
        start_media_streaming=True,
        enable_bidirectional=True,
        # NOT DEPLOYED IN AZURE
        #audio_format=AudioFormat.PCM16K_MONO,
    )

    logging.info(f"Responding call with WS: {WEBSOCKET_URL}")

    call_props = client.answer_call(
        incoming_call_context=incoming_call_context,
        callback_url=CALLBACK_URL,
        media_streaming=media_streaming_options,
        operation_context="incomingCall",
    )

    logging.info(f"Call answered. CallConnectionId: {call_props.call_connection_id}")
