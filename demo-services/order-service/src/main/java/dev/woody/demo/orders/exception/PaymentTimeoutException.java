package dev.woody.demo.orders.exception;

import java.util.UUID;

import lombok.Getter;

@Getter
public class PaymentTimeoutException extends RuntimeException {

    private final UUID orderId;

    public PaymentTimeoutException(UUID orderId) {
        super("Simulated payment dependency timeout");
        this.orderId = orderId;
    }
}
