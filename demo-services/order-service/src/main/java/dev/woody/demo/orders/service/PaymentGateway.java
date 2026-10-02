package dev.woody.demo.orders.service;

import java.util.UUID;

public interface PaymentGateway {

    void authorize(UUID orderId);
}