"""
Інтеграція з WayForPay
"""
import hashlib
import hmac
import time
import uuid
import json
from typing import Optional
import config


def _signature(data: list) -> str:
    """Генерація підпису HMAC MD5"""
    sign_string = ";".join(str(v) for v in data)
    return hmac.new(
        config.WAYFORPAY_SECRET_KEY.encode("utf-8"),
        sign_string.encode("utf-8"),
        hashlib.md5,
    ).hexdigest()


def create_payment_link(
    amount: float,
    product_name: str,
    order_reference: Optional[str] = None,
    client_email: str = "",
    client_phone: str = "",
    is_trial: bool = False,
    regular_mode: str = "monthly",
    regular_amount: Optional[float] = None,
    date_next: str = "",
    date_end: str = "",
    regular_count: Optional[int] = None,
    return_url: str = "",
    service_url: str = "",
) -> dict:
    """
    Створює дані для форми оплати WayForPay.
    Повертає dict з полями для POST на https://secure.wayforpay.com/pay
    """
    order_ref = order_reference or f"order_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    order_date = int(time.time())

    product_names = [product_name]
    product_prices = [amount]
    product_counts = [1]

    sign_data = [
        config.WAYFORPAY_MERCHANT_ACCOUNT,
        config.WAYFORPAY_DOMAIN,
        order_ref,
        order_date,
        amount,
        "UAH",
        *product_names,
        *product_counts,
        *product_prices,
    ]
    merchant_signature = _signature(sign_data)

    data = {
        "merchantAccount": config.WAYFORPAY_MERCHANT_ACCOUNT,
        "merchantDomainName": config.WAYFORPAY_DOMAIN,
        "merchantSignature": merchant_signature,
        "merchantAuthType": "SimpleSignature",
        "orderReference": order_ref,
        "orderDate": order_date,
        "amount": amount,
        "currency": "UAH",
        "productName[]": product_names,
        "productPrice[]": product_prices,
        "productCount[]": product_counts,
        "language": "UA",
    }

    if client_email:
        data["clientEmail"] = client_email
    if client_phone:
        data["clientPhone"] = client_phone
    if return_url:
        data["returnUrl"] = return_url
    if service_url:
        data["serviceUrl"] = service_url

    # Рекурентний платіж - щомісячне списання
    if regular_mode and regular_mode.lower() != "none":
        # preset: клієнт не може редагувати параметри регулярного платежу на сторінці оплати
        data["regularBehavior"] = "preset"
        data["regularMode"] = regular_mode
        data["regularOn"] = "1"
        data["regularAmount"] = regular_amount if regular_amount is not None else amount
        if date_next:
            data["dateNext"] = date_next
        # Вимога WayForPay: для створення регулярного правила має бути задано
        # або dateEnd, або regularCount.
        if date_end:
            data["dateEnd"] = date_end
        if regular_count is not None:
            data["regularCount"] = int(regular_count)

    return {"data": data, "order_reference": order_ref}


def verify_callback_signature(
    merchant_account: str,
    order_reference: str,
    amount,
    currency: str,
    auth_code: str,
    card_pan: str,
    transaction_status: str,
    reason_code,
    received_signature: str,
) -> bool:
    """
    Перевірка підпису callback від WayForPay.

    Важливо: WayForPay підписує значення як рядки. Тому `amount` / `reason_code`
    приймаємо без примусових перетворень у float/int (щоб не зламати форматування).
    """
    sign_data = [
        str(merchant_account or ""),
        str(order_reference or ""),
        str(amount or ""),
        str(currency or ""),
        str(auth_code or ""),
        str(card_pan or ""),
        str(transaction_status or ""),
        str(reason_code or ""),
    ]
    expected = _signature(sign_data)
    return hmac.compare_digest(expected, received_signature)


def create_charge_request(rec_token: str, amount: float, order_reference: str, 
                         product_name: str, product_count: int = 1) -> dict:
    """
    Charge - повторне списання по збереженому recToken
    Використовується для retry при неуспішній оплаті
    """
    order_date = int(time.time())
    sign_data = [
        config.WAYFORPAY_MERCHANT_ACCOUNT,
        config.WAYFORPAY_DOMAIN,
        order_reference,
        order_date,
        amount,
        "UAH",
        product_name,
        product_count,
        amount,
    ]
    merchant_signature = _signature(sign_data)

    return {
        "transactionType": "Charge",
        "merchantAccount": config.WAYFORPAY_MERCHANT_ACCOUNT,
        "merchantAuthType": "SimpleSignature",
        "merchantDomainName": config.WAYFORPAY_DOMAIN,
        "merchantTransactionType": "SALE",
        "merchantTransactionSecureType": "AUTO",
        "merchantSignature": merchant_signature,
        "apiVersion": 1,
        "orderReference": order_reference,
        "orderDate": order_date,
        "amount": amount,
        "currency": "UAH",
        "productName[]": [product_name],
        "productPrice[]": [amount],
        "productCount[]": [product_count],
        "recToken": rec_token,
    }


def create_regular_status_request(order_reference: str) -> dict:
    """Перевірка статусу регулярного платежу"""
    sign_data = [
        config.WAYFORPAY_MERCHANT_ACCOUNT,
        order_reference,
    ]
    merchant_signature = _signature(sign_data)
    return {
        "transactionType": "CHECK_STATUS",
        "merchantAccount": config.WAYFORPAY_MERCHANT_ACCOUNT,
        "orderReference": order_reference,
        "merchantSignature": merchant_signature,
        "apiVersion": 1,
    }


def create_regular_delete_request(order_reference: str) -> dict:
    """Скасування рекурентного платежу — REMOVE via regularApi"""
    merchant_password = getattr(config, "WAYFORPAY_MERCHANT_PASSWORD", None) or config.WAYFORPAY_SECRET_KEY
    return {
        "requestType": "REMOVE",
        "merchantAccount": config.WAYFORPAY_MERCHANT_ACCOUNT,
        "merchantPassword": merchant_password,
        "orderReference": order_reference,
    }


def create_regular_status_api_request(order_reference: str) -> dict:
    """Статус регулярного правила через regularApi (requestType=STATUS)."""
    merchant_password = getattr(config, "WAYFORPAY_MERCHANT_PASSWORD", None) or config.WAYFORPAY_SECRET_KEY
    return {
        "requestType": "STATUS",
        "merchantAccount": config.WAYFORPAY_MERCHANT_ACCOUNT,
        "merchantPassword": merchant_password,
        "orderReference": order_reference,
    }


def create_regular_change_request(
    order_reference: str,
    *,
    regular_mode: str,
    amount: float,
    currency: str,
    date_begin: str,
    date_end: str,
) -> dict:
    """Зміна параметрів регулярного правила через regularApi (requestType=CHANGE)."""
    merchant_password = getattr(config, "WAYFORPAY_MERCHANT_PASSWORD", None) or config.WAYFORPAY_SECRET_KEY
    return {
        "requestType": "CHANGE",
        "merchantAccount": config.WAYFORPAY_MERCHANT_ACCOUNT,
        "merchantPassword": merchant_password,
        "regularMode": regular_mode,
        "amount": amount,
        "currency": currency,
        "dateBegin": date_begin,
        "dateEnd": date_end,
        "orderReference": order_reference,
    }
