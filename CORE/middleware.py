import logging

from django.conf import settings
from django.http import JsonResponse


logger = logging.getLogger(__name__)


class ApiKeyMiddleware:
	"""Require X-API-KEY on every request and log request/response details."""

	def __init__(self, get_response):
		self.get_response = get_response

	def __call__(self, request):
		request_path = request.path
		exempt_prefixes = getattr(settings, "API_KEY_EXEMPT_PATH_PREFIXES", ())
		provided_key = request.headers.get("X-API-KEY")
		expected_key = getattr(settings, "X_API_KEY", None)

		logger.info(
			"Incoming request method=%s path=%s",
			request.method,
			request.get_full_path(),
		)

		if any(request_path.startswith(prefix) for prefix in exempt_prefixes):
			logger.info(
				"Bypassing API key check for exempt path method=%s path=%s",
				request.method,
				request.get_full_path(),
			)
			response = self.get_response(request)
			logger.info(
				"Outgoing response method=%s path=%s status=%s",
				request.method,
				request.get_full_path(),
				response.status_code,
			)
			return response

		if not provided_key:
			logger.warning(
				"Rejected request (missing API key) method=%s path=%s",
				request.method,
				request.get_full_path(),
			)
			return JsonResponse({"detail": "X-API-KEY header is required."}, status=401)

		if not expected_key:
			logger.error(
				"Server misconfiguration: X_API_KEY environment variable is not set."
			)
			return JsonResponse({"detail": "Server API key is not configured."}, status=500)

		if provided_key != expected_key:
			logger.warning(
				"Rejected request (invalid API key) method=%s path=%s",
				request.method,
				request.get_full_path(),
			)
			return JsonResponse({"detail": "Invalid API key."}, status=401)

		response = self.get_response(request)
		logger.info(
			"Outgoing response method=%s path=%s status=%s",
			request.method,
			request.get_full_path(),
			response.status_code,
		)
		return response
