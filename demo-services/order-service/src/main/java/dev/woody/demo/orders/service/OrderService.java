package dev.woody.demo.orders.service;

import java.util.UUID;

import org.springframework.stereotype.Service;

import lombok.AllArgsConstructor;
import lombok.extern.slf4j.Slf4j;

@Service
@AllArgsConstructor
@Slf4j
public class OrderService {
    
    private final PaymentGateway paymentGateway;

    public UUID createOrder(String productId, Integer quantity) {
        var orderId = UUID.randomUUID();

        log.info(
            "Order request received: orderId={}, productId={}, quantity={}",
            orderId,
            productId,
            quantity
        );

        paymentGateway.authorize(orderId);

        log.info("Order accepted: orderId={}", orderId);

        return orderId;
    }
}