import unittest

from hyperreview import intake
from hyperreview.model_contract import ContractError, prepare_request, validate_request
from test_model_contract import pack, source, redigest_request


class TransmissionTests(unittest.TestCase):
    def test_prepared_request_is_valid(self):
        request = prepare_request(pack())
        self.assertIs(validate_request(request), request)

    def test_rehashed_service_metadata_cannot_bypass_boundary(self):
        for field in ("scope", "limitations"):
            request = prepare_request(pack())
            request[field] = ['password="sensitive-value"']
            redigest_request(request)
            with self.assertRaises(ContractError):
                validate_request(request)
        request = prepare_request(pack())
        request["omissions"] = [{"id": None, "path": "src/app.py", "side": "after",
                                "reason": "upload credentials"}]
        redigest_request(request)
        with self.assertRaises(ContractError):
            validate_request(request)

    def test_rehashed_sensitive_source_cannot_bypass_filter(self):
        request = prepare_request(pack())
        replacement = prepare_request(pack([source("after", "safe replacement\n")]))["sources"][0]
        content = 'password="sensitive-value"\n'
        replacement["content"] = content
        import hashlib
        replacement["content_sha256"] = hashlib.sha256(content.encode()).hexdigest()
        replacement["id"] = "src_" + hashlib.sha256(intake.encoded([
            replacement["revision"], replacement["path"], replacement["content_sha256"]])).hexdigest()
        request["sources"] = [replacement]
        request["source_selection"]["included_source_bytes"] = len(intake.encoded(content))
        redigest_request(request)
        with self.assertRaises(ContractError):
            validate_request(request)
