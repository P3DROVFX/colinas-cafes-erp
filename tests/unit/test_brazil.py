import pytest

from domain.brazil import PersonType, is_valid_cnpj, is_valid_cpf, is_valid_document

VALID_CPF = "529.982.247-25"
VALID_CNPJ = "11.222.333/0001-81"


@pytest.mark.parametrize("cpf", [VALID_CPF, "52998224725", "111.444.777-35"])
def test_valid_cpf(cpf):
    assert is_valid_cpf(cpf)


@pytest.mark.parametrize("cpf", ["529.982.247-24", "111.111.111-11", "123", ""])
def test_invalid_cpf(cpf):
    assert not is_valid_cpf(cpf)


@pytest.mark.parametrize("cnpj", [VALID_CNPJ, "11222333000181"])
def test_valid_cnpj(cnpj):
    assert is_valid_cnpj(cnpj)


@pytest.mark.parametrize("cnpj", ["11.222.333/0001-80", "00.000.000/0000-00", "1122233300018"])
def test_invalid_cnpj(cnpj):
    assert not is_valid_cnpj(cnpj)


def test_document_validation_follows_person_type():
    assert is_valid_document(PersonType.INDIVIDUAL, VALID_CPF)
    assert not is_valid_document(PersonType.COMPANY, VALID_CPF)
    assert is_valid_document(PersonType.COMPANY, VALID_CNPJ)
