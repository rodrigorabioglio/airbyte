#
# Copyright (c) 2023 Airbyte, Inc., all rights reserved.
#

import json
from pathlib import Path

import pytest
import yaml
from metadata_service import gcs_upload
from metadata_service.constants import METADATA_FILE_NAME, DOC_FILE_NAME
from metadata_service.models.generated.ConnectorMetadataDefinitionV0 import ConnectorMetadataDefinitionV0
from metadata_service.models.transform import to_json_sanitized_dict
from metadata_service.validators.metadata_validator import ValidatorOptions
from pydash.objects import get

# Version exists by default, but "666" is bad! (6.0.0 too since breaking changes regex tho)
MOCK_VERSIONS_THAT_DO_NOT_EXIST = ["6.6.6", "6.0.0"]
MOCK_LOCAL_DOC_PATH = "docs/integrations/sources/alloydb.md"

def stub_is_image_on_docker_hub(image_name: str, version: str) -> bool:
    return "exists" in image_name and version not in MOCK_VERSIONS_THAT_DO_NOT_EXIST


def setup_upload_mocks(mocker, version_blob_md5_hash, latest_blob_md5_hash, local_file_md5_hash, doc_local_file_md5_hash, doc_version_blob_md5_hash, doc_latest_blob_md5_hash, metadata_file_path, doc_file_path):
    # Mock dockerhub
    mocker.patch("metadata_service.validators.metadata_validator.is_image_on_docker_hub", side_effect=stub_is_image_on_docker_hub)

    # Mock GCS
    service_account_json = '{"type": "service_account"}'
    mocker.patch.dict("os.environ", {"GCS_CREDENTIALS": service_account_json})
    mock_credentials = mocker.Mock()
    mock_storage_client = mocker.Mock()

    latest_blob_exists = latest_blob_md5_hash is not None
    version_blob_exists = version_blob_md5_hash is not None
    doc_version_blob_exists = doc_version_blob_md5_hash is not None
    doc_latest_blob_exists = doc_latest_blob_md5_hash is not None

    mock_version_blob = mocker.Mock(exists=mocker.Mock(return_value=version_blob_exists), md5_hash=version_blob_md5_hash)
    mock_latest_blob = mocker.Mock(exists=mocker.Mock(return_value=latest_blob_exists), md5_hash=latest_blob_md5_hash)
    mock_doc_version_blob = mocker.Mock(exists=mocker.Mock(return_value=doc_version_blob_exists), md5_hash=doc_version_blob_md5_hash)
    mock_doc_latest_blob = mocker.Mock(exists=mocker.Mock(return_value=doc_latest_blob_exists), md5_hash=doc_latest_blob_md5_hash)
    mock_bucket = mock_storage_client.bucket.return_value
    mock_bucket.blob.side_effect = [mock_version_blob, mock_doc_version_blob, mock_latest_blob, mock_doc_latest_blob]

    mocker.patch.object(gcs_upload.service_account.Credentials, "from_service_account_info", mocker.Mock(return_value=mock_credentials))
    mocker.patch.object(gcs_upload.storage, "Client", mocker.Mock(return_value=mock_storage_client))

    # Mock md5 hash
    def side_effect_compute_gcs_md5(file_path):
        if str(file_path) == str(metadata_file_path):
            return local_file_md5_hash
        elif str(file_path) == str(doc_file_path):
            return doc_local_file_md5_hash
        else:
            raise ValueError(f"Unexpected path: {file_path}")

    mocker.patch.object(gcs_upload, "compute_gcs_md5", side_effect=side_effect_compute_gcs_md5)

    return {
        "mock_credentials": mock_credentials,
        "mock_storage_client": mock_storage_client,
        "mock_bucket": mock_bucket,
        "mock_version_blob": mock_version_blob,
        "mock_latest_blob": mock_latest_blob,
        "mock_doc_version_blob": mock_doc_version_blob,
        "mock_doc_latest_blob": mock_doc_latest_blob,
        "service_account_json": service_account_json,
    }


@pytest.mark.parametrize(
    "version_blob_md5_hash, latest_blob_md5_hash, local_file_md5_hash, local_doc_file_md5_hash, doc_version_blob_md5_hash, doc_latest_blob_md5_hash",
    [
        pytest.param(None, "same_md5_hash", "same_md5_hash", "same_doc_md5_hash", "same_doc_md5_hash", "same_doc_md5_hash", id="Version blob does not exist: Version blob should be uploaded."),
        pytest.param("same_md5_hash", None, "same_md5_hash", "same_doc_md5_hash", "same_doc_md5_hash", "same_doc_md5_hash", id="Latest blob does not exist: Latest blob should be uploaded."),
        pytest.param(None, None, "same_md5_hash", "same_doc_md5_hash", "same_doc_md5_hash", "same_doc_md5_hash", id="Latest blob and Version blob does not exist: both should be uploaded."),
        pytest.param(
            "different_md5_hash", "same_md5_hash", "same_md5_hash", "same_doc_md5_hash", "same_doc_md5_hash", "same_doc_md5_hash", id="Version blob does not match: Version blob should be uploaded."
        ),
        pytest.param(
            "same_md5_hash",
            "same_md5_hash",
            "same_md5_hash",
            "same_doc_md5_hash",
            "same_doc_md5_hash",
            "same_doc_md5_hash",
            id="Version blob and Latest blob match, and version and latest doc blobs match: no upload should happen.",
        ),
        pytest.param(
            "same_md5_hash", "different_md5_hash", "same_md5_hash", "same_doc_md5_hash", "same_doc_md5_hash", "same_doc_md5_hash", id="Latest blob does not match: Latest blob should be uploaded."
        ),
        pytest.param(
            "same_md5_hash",
            "same_md5_hash",
            "different_md5_hash",
            "same_doc_md5_hash",
            "same_doc_md5_hash",
            "same_doc_md5_hash",
            id="Latest blob and Version blob does not match: both should be uploaded.",
        ),
        pytest.param(
            "same_md5_hash",
            "same_md5_hash",
            "same_md5_hash",
            "same_doc_md5_hash",
            None,
            "same_doc_md5_hash",
            id="Version doc blob does not exist: Doc version blob should be uploaded.",
        ),
        pytest.param(
            "same_md5_hash",
            "same_md5_hash",
            "same_md5_hash",
            "same_doc_md5_hash",
            "same_doc_md5_hash",
            None,
            id="Latest doc blob does not exist: Doc latest blob should be uploaded.",
        ),
        pytest.param(
            "same_md5_hash",
            "same_md5_hash",
            "same_md5_hash",
            "same_doc_md5_hash",
            "different_doc_md5_hash",
            "same_doc_md5_hash",
            id="Version doc blob does not match: Doc version blob should be uploaded.",
        ),
        pytest.param(
            "same_md5_hash",
            "same_md5_hash",
            "same_md5_hash",
            "same_doc_md5_hash",
            "same_doc_md5_hash",
            "different_doc_md5_hash",
            id="Latest doc blob does not match: Doc version blob should be uploaded.",
        ),
    ],
)
def test_upload_metadata_to_gcs_valid_metadata(
    mocker, valid_metadata_upload_files, valid_doc_file, version_blob_md5_hash, latest_blob_md5_hash, local_file_md5_hash, local_doc_file_md5_hash, doc_version_blob_md5_hash, doc_latest_blob_md5_hash
):
    mocker.spy(gcs_upload, "_version_upload")
    mocker.spy(gcs_upload, "_latest_upload")
    mocker.spy(gcs_upload, "_doc_upload")

    for valid_metadata_upload_file in valid_metadata_upload_files:
        metadata_file_path = Path(valid_metadata_upload_file)
        metadata = ConnectorMetadataDefinitionV0.parse_obj(yaml.safe_load(metadata_file_path.read_text()))

        doc_file_path = Path(valid_doc_file)

        mocks = setup_upload_mocks(mocker, version_blob_md5_hash, latest_blob_md5_hash, local_file_md5_hash, local_doc_file_md5_hash, doc_version_blob_md5_hash, doc_latest_blob_md5_hash, metadata_file_path, valid_doc_file)

        expected_version_key = f"metadata/{metadata.data.dockerRepository}/{metadata.data.dockerImageTag}/{METADATA_FILE_NAME}"
        expected_latest_key = f"metadata/{metadata.data.dockerRepository}/latest/{METADATA_FILE_NAME}"
        expected_version_doc_key = f"metadata/{metadata.data.dockerRepository}/{metadata.data.dockerImageTag}/{DOC_FILE_NAME}"
        expected_latest_doc_key = f"metadata/{metadata.data.dockerRepository}/latest/{DOC_FILE_NAME}"

        latest_blob_exists = latest_blob_md5_hash is not None
        version_blob_exists = version_blob_md5_hash is not None
        doc_version_blob_exists = doc_version_blob_md5_hash is not None
        doc_latest_blob_exists = doc_latest_blob_md5_hash is not None

        # Call function under tests

        upload_info = gcs_upload.upload_metadata_to_gcs(
            "my_bucket",
            metadata_file_path,
            validator_opts=ValidatorOptions(doc_path=valid_doc_file)
        )

        # Assertions

        gcs_upload._version_upload.assert_called()
        gcs_upload._latest_upload.assert_called()
        gcs_upload._doc_upload.assert_called()

        gcs_upload.service_account.Credentials.from_service_account_info.assert_called_with(json.loads(mocks["service_account_json"]))
        mocks["mock_storage_client"].bucket.assert_called_with("my_bucket")
        mocks["mock_bucket"].blob.assert_has_calls([mocker.call(expected_version_key), mocker.call(expected_version_doc_key), mocker.call(expected_latest_key), mocker.call(expected_latest_doc_key)])

        version_metadata_uploaded_file = next((file for file in upload_info.uploaded_files if file.id == "version_metadata"), None)
        assert version_metadata_uploaded_file, "version_metadata not found in uploaded files."
        assert version_metadata_uploaded_file.blob_id == mocks["mock_version_blob"].id

        doc_version_uploaded_file = next((file for file in upload_info.uploaded_files if file.id == "doc_version"), None)
        assert doc_version_uploaded_file, "doc_version not found in uploaded files."
        assert doc_version_uploaded_file.blob_id == mocks["mock_doc_version_blob"].id

        doc_latest_uploaded_file = next((file for file in upload_info.uploaded_files if file.id == "doc_latest"), None)
        assert doc_latest_uploaded_file, "doc_latest not found in uploaded files."
        assert doc_latest_uploaded_file.blob_id == mocks["mock_doc_latest_blob"].id

        if not version_blob_exists:
            mocks["mock_version_blob"].upload_from_filename.assert_called_with(metadata_file_path)
            assert upload_info.metadata_uploaded

        if not latest_blob_exists:
            mocks["mock_latest_blob"].upload_from_filename.assert_called_with(metadata_file_path)
            assert upload_info.metadata_uploaded
        
        if not doc_version_blob_exists:
            mocks["mock_doc_version_blob"].upload_from_filename.assert_called_with(doc_file_path)
            assert doc_version_uploaded_file.uploaded

        if not doc_latest_blob_exists:
            mocks["mock_doc_latest_blob"].upload_from_filename.assert_called_with(doc_file_path)
            assert doc_latest_uploaded_file.uploaded

        if version_blob_md5_hash != local_file_md5_hash:
            mocks["mock_version_blob"].upload_from_filename.assert_called_with(metadata_file_path)
            assert upload_info.metadata_uploaded

        if latest_blob_md5_hash != local_file_md5_hash:
            mocks["mock_latest_blob"].upload_from_filename.assert_called_with(metadata_file_path)
            assert upload_info.metadata_uploaded

        if doc_version_blob_md5_hash != local_doc_file_md5_hash:
            mocks["mock_doc_version_blob"].upload_from_filename.assert_called_with(doc_file_path)
            assert doc_version_uploaded_file.uploaded

        if doc_latest_blob_md5_hash != local_doc_file_md5_hash:
            mocks["mock_doc_latest_blob"].upload_from_filename.assert_called_with(doc_file_path)
            assert doc_latest_uploaded_file.uploaded

        # clear the call count
        gcs_upload._latest_upload.reset_mock()
        gcs_upload._version_upload.reset_mock()
        gcs_upload._doc_upload.reset_mock()


def test_upload_metadata_to_gcs_non_existent_metadata_file(valid_doc_file):
    metadata_file_path = Path("./i_dont_exist.yaml")
    with pytest.raises(FileNotFoundError):
        gcs_upload.upload_metadata_to_gcs(
            "my_bucket",
            metadata_file_path,
            validator_opts=ValidatorOptions(doc_path=valid_doc_file),
        )


def test_upload_invalid_metadata_to_gcs(invalid_metadata_yaml_files, valid_doc_file):
    for invalid_metadata_file in invalid_metadata_yaml_files:
        metadata_file_path = Path(invalid_metadata_file)
        # If your test fails with 'Please set the DOCKER_HUB_USERNAME and DOCKER_HUB_PASSWORD environment variables.'
        # then your test data passed validation when it shouldn't have!
        with pytest.raises(ValueError, match="Validation error"):
            gcs_upload.upload_metadata_to_gcs(
                "my_bucket",
                metadata_file_path,
                validator_opts=ValidatorOptions(doc_path=valid_doc_file),
            )


def test_upload_metadata_to_gcs_invalid_docker_images(mocker, invalid_metadata_upload_files, valid_doc_file):
    setup_upload_mocks(mocker, None, None, "new_md5_hash", None, None, None, None, None)

    # Test that all invalid metadata files throw a ValueError
    for invalid_metadata_file in invalid_metadata_upload_files:
        metadata_file_path = Path(invalid_metadata_file)
        with pytest.raises(ValueError, match="does not exist in DockerHub"):
            gcs_upload.upload_metadata_to_gcs(
                "my_bucket",
                metadata_file_path,
                validator_opts=ValidatorOptions(doc_path=valid_doc_file),
            )


def test_upload_metadata_to_gcs_with_prerelease(mocker, valid_metadata_upload_files, valid_doc_file):
    # Arrange
    setup_upload_mocks(mocker, "new_md5_hash1", "new_md5_hash2", "new_md5_hash3", None, None, None, None, None)
    mocker.patch("metadata_service.gcs_upload._latest_upload", return_value=(True, "someid"))
    mocker.patch("metadata_service.gcs_upload.upload_file_if_changed", return_value=(True, "someid"))
    mocker.spy(gcs_upload, "_version_upload")
    doc_upload_spy = mocker.spy(gcs_upload, "_doc_upload")

    for valid_metadata_upload_file in valid_metadata_upload_files:
        # Assuming there is a valid metadata file in the list, if not, you might need to create one
        metadata_file_path = Path(valid_metadata_upload_file)
        prerelease_image_tag = "1.5.6-dev.f80318f754"

        gcs_upload.upload_metadata_to_gcs(
            "my_bucket",
            metadata_file_path,
            ValidatorOptions(doc_path=valid_doc_file, prerelease_tag=prerelease_image_tag),
        )

        gcs_upload._latest_upload.assert_not_called()

        # Assert that _version_upload is called and the third argument is prerelease_image_tag
        # Ignore the first and second arguments (_ and __ are often used as placeholder variable names in Python when you don't care about the value)
        _, __, tmp_metadata_file_path = gcs_upload._version_upload.call_args[0]
        assert prerelease_image_tag in str(tmp_metadata_file_path)

        # Assert that _doc_upload is only called twice, both with latest set to False
        assert doc_upload_spy.call_count == 2
        assert doc_upload_spy.call_args_list[0].args[-2] == False
        assert doc_upload_spy.call_args_list[1].args[-2] == False
        doc_upload_spy.reset_mock()

        # Verify the tmp metadata is overridden
        assert tmp_metadata_file_path.exists(), f"{tmp_metadata_file_path} does not exist"

        # verify that the metadata is overrode
        tmp_metadata, error = gcs_upload.validate_and_load(tmp_metadata_file_path, [], validator_opts=ValidatorOptions(doc_path=valid_doc_file))
        tmp_metadata_dict = to_json_sanitized_dict(tmp_metadata, exclude_none=True)
        assert tmp_metadata_dict["data"]["dockerImageTag"] == prerelease_image_tag
        for registry in get(tmp_metadata_dict, "data.registries", {}).values():
            if "dockerImageTag" in registry:
                assert registry["dockerImageTag"] == prerelease_image_tag
